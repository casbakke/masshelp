"""Twilio SMS/MMS webhook (SPEC 5.3). Reply with empty TwiML right away, then run the
agent turn in the background and send the reply with the REST API.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, Response

from masshelp.agent.runner import UserInput
from masshelp.cases import get_or_create_case
from masshelp.docs.ingest import IncomingMedia
from masshelp.messaging import send_case_sms
from masshelp.store.db import log_event
from masshelp.store.models import Case
from masshelp.util.phone import normalize_phone

log = logging.getLogger(__name__)
router = APIRouter()

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout"}
START_WORDS = {"start", "unstop"}
MAX_MEDIA_BYTES = 10_000_000


def twiml() -> Response:
    return Response(content=EMPTY_TWIML, media_type="application/xml")


def signature_ok(services, request: Request, form: dict[str, str]) -> bool:
    settings = services.settings
    if not settings.twilio_validate:
        return True
    if not settings.twilio_auth_token:
        log.error("TWILIO_VALIDATE is on but TWILIO_AUTH_TOKEN is not set; rejecting")
        return False
    from twilio.request_validator import RequestValidator

    url = settings.public_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    signature = request.headers.get("X-Twilio-Signature", "")
    return RequestValidator(settings.twilio_auth_token).validate(url, form, signature)


async def download_media(services, url: str, content_type: str) -> IncomingMedia | None:
    settings = services.settings
    auth = (settings.twilio_account_sid, settings.twilio_auth_token) if settings.twilio_account_sid else None
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, auth=auth)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("media download failed: %s", exc)
        return None
    if len(resp.content) > MAX_MEDIA_BYTES:
        return None
    return IncomingMedia(data=resp.content, content_type=content_type or resp.headers.get("content-type", ""), source_url=url)


@router.post("/twilio/sms")
async def twilio_sms(request: Request, background: BackgroundTasks) -> Response:
    services = request.app.state.services
    form = {k: str(v) for k, v in (await request.form()).items()}
    if not signature_ok(services, request, form):
        return Response(status_code=403, content="invalid signature")

    phone = normalize_phone(form.get("From"))
    if not phone:
        return twiml()
    body = (form.get("Body") or "").strip()
    try:
        num_media = int(form.get("NumMedia") or 0)
    except ValueError:
        num_media = 0
    media_refs = [(form.get(f"MediaUrl{i}", ""), form.get(f"MediaContentType{i}", "")) for i in range(num_media)]
    media_refs = [(u, c) for u, c in media_refs if u]

    keyword = body.lower().strip(" .!")
    if keyword in STOP_WORDS or keyword in START_WORDS:
        with services.db.session() as s:
            case = get_or_create_case(s, services.masshealth, phone, body)
            case.opted_out = keyword in STOP_WORDS
            s.add(case)
            s.commit()
            log_event(s, case.id, "opt_out" if case.opted_out else "opt_in", {})
        return twiml()  # Twilio sends its own STOP/START reply (R4)

    background.add_task(process_sms, services, phone, body, media_refs)
    return twiml()


async def process_sms(services, phone: str, body: str, media_refs: list[tuple[str, str]]) -> None:
    """Serialized per phone number so two quick texts don't race."""
    async with services.locks.get(f"phone:{phone}"):
        with services.db.session() as s:
            case = get_or_create_case(s, services.masshealth, phone, body)
            case_id = case.id
            if case.opted_out:
                log_event(s, case_id, "sms_ignored_opted_out", {})
                return
        media = [m for m in [await download_media(services, u, c) for u, c in media_refs] if m]
        reply = ""
        async for chunk in services.runner.handle(case_id, "sms", UserInput(text=body, media=media)):
            reply += chunk
        with services.db.session() as s:
            case = s.get(Case, case_id)
            await send_case_sms(services.messenger, s, case, reply, limit=services.settings.sms_split_chars)
