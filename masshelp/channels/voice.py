"""Vapi custom LLM adapter (SPEC 5.3): POST /vapi/chat/completions, OpenAI-style SSE out.

Vapi does speech-to-text and text-to-speech. We take the latest user utterance, run
our own tool loop server-side, and stream only the spoken text back. Our SQLite
transcript is the source of truth for history, not Vapi's `messages`.
[VERIFY] payload shape: call.id and call.customer.number. Unknown shapes are logged.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from masshelp.agent.runner import UserInput
from masshelp.cases import get_or_create_case
from masshelp.store.db import log_event
from masshelp.store.models import Case
from masshelp.util.phone import normalize_phone

log = logging.getLogger(__name__)
router = APIRouter()

# Configure the same text as the Vapi assistant's firstMessage (R32).
VOICE_GREETING = (
    "Hi, this is MassHelp, a free automated assistant. I'm not MassHealth. "
    "I can help you answer MassHealth's work rule letter. Para español, diga español."
)


def authorized(services, request: Request) -> bool:
    secret = services.settings.vapi_secret
    if not secret:
        return True
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    return hmac.compare_digest(token, secret) or hmac.compare_digest(header, secret)


def latest_user_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            return str(content or "")
    return ""


def chunk(completion_id: str, model: str, delta: dict, finish: str | None = None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/vapi/chat/completions")
async def vapi_chat(request: Request) -> Response:
    services = request.app.state.services
    if not authorized(services, request):
        return Response(status_code=401, content="unauthorized")
    body = await request.json()
    call = body.get("call") or {}
    call_id = call.get("id") or "no-call-id"
    phone = normalize_phone(((call.get("customer") or {}).get("number"))) or normalize_phone(
        services.settings.vapi_default_phone)
    model = body.get("model") or "masshelp"
    stream = body.get("stream", True)
    text = latest_user_text(body.get("messages") or [])

    if not phone:
        with services.db.session() as s:
            log_event(s, None, "vapi_no_phone", {"keys": list(body), "call_keys": list(call)})
        return JSONResponse({"error": "no caller number"}, status_code=400)

    async with services.locks.get(f"phone:{phone}"):
        with services.db.session() as s:
            case = get_or_create_case(s, services.masshealth, phone, text)
            case_id = case.id
            new_call = case.last_call_id != call_id
            if new_call:
                case.last_call_id = call_id
                s.add(case)
                s.commit()
                log_event(s, case_id, "call_started", {"call_id": call_id})
    if new_call:
        # The greeting was spoken by Vapi (firstMessage); keep our transcript in sync.
        services.runner.add_assistant_note(case_id, "voice", VOICE_GREETING)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    agen = services.runner.handle(case_id, "voice", UserInput(text=text))

    if not stream:
        reply = "".join([c async for c in agen])
        return JSONResponse({
            "id": completion_id, "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        })

    async def sse():
        yield chunk(completion_id, model, {"role": "assistant", "content": ""})
        async for piece in agen:
            yield chunk(completion_id, model, {"content": piece})
        yield chunk(completion_id, model, {}, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def case_for_call(services, call_id: str) -> Case | None:
    from sqlmodel import select

    with services.db.session() as s:
        return s.exec(select(Case).where(Case.last_call_id == call_id)).first()
