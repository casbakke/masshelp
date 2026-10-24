"""Tools exposed to Claude (SPEC 5.5). Strict JSON schemas; every tool returns a
JSON-serializable dict. Tools that touch member data refuse until identity is verified.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, col, select

from masshelp.answers import ANSWER_FIELDS, FIELD_HELP, AnswerError, answers_for_display, facts_from_answers, latest_answers, parse_value, save_answer
from masshelp.cases import case_member, identity_locked, identity_valid
from masshelp.docs.ingest import case_documents, refresh_reconciliation
from masshelp.forms.afvi import FinalStamp, us_date
from masshelp.forms.build import build_form, file_url, form_support, write_pdf
from masshelp.i18n import t
from masshelp.messaging import send_case_sms
from masshelp.rules.engine import evaluate
from masshelp.rules.models import Evaluation, Status, YearMonth
from masshelp.store.db import log_event
from masshelp.store.models import Case, CaseStatus, Consent, FormPdf, Submission
from masshelp.util.dates import parse_date, today, utcnow
from masshelp.util.lang import base_language
from masshelp.util.redact import redact, redact_obj

log = logging.getLogger(__name__)

NO_IDENTITY_TOOLS = {"verify_identity", "set_language", "handoff_to_human"}
SLOW_TOOLS = {"prepare_form", "submit_to_masshealth", "request_document", "send_confirmation_sms"}


@dataclass
class ToolContext:
    services: Any
    case_id: str
    channel: str  # sms or voice
    user_message_id: int | None
    user_text: str  # latest member message (redacted), used as the consent reply


# ---------------------------------------------------------------- schemas


def _tool(name: str, description: str, properties: dict | None = None) -> dict:
    properties = properties or {}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def tool_definitions(rules) -> list[dict]:
    field_help = "; ".join(f"{k}: {v}" for k, v in FIELD_HELP.items())
    proof_ids = [p for p in rules.proof_types if p != "attestation"]
    return [
        _tool(
            "verify_identity",
            "Check the member's date of birth (and MassHealth ID if their phone number is not on file). "
            "Call as soon as the member gives these. Never reveal case details before this returns verified=true.",
            {
                "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
                "masshealth_id": {**_NULLABLE_STR, "description": "Only if the phone number is not on file, e.g. MH-DEMO-000123"},
            },
        ),
        _tool("get_case_status", "Member first name, language, what MassHealth asked for, deadline, answers so far, documents, and next steps."),
        _tool(
            "record_answers",
            "Save facts as soon as the member says them. Values are strings: numbers like '900', booleans 'true'/'false', "
            "months 'YYYY-MM', enums as listed. Returns the updated answers and the rules engine result. " + field_help,
            {
                "answers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": ANSWER_FIELDS},
                            "value": {"type": "string"},
                        },
                        "required": ["field", "value"],
                        "additionalProperties": False,
                    },
                }
            },
        ),
        _tool(
            "evaluate_requirement",
            "Run the deterministic rules engine. The ONLY source of outcomes. month is YYYY-MM or null for the month MassHealth asked about.",
            {"month": _NULLABLE_STR},
        ),
        _tool(
            "request_document",
            "Tell the member what proof to send. On a call this texts them the instructions. Returns alternatives if they don't have it.",
            {"doc_type": {"type": "string", "enum": proof_ids}},
        ),
        _tool("get_documents", "What was read from each photo or file the member sent, and any mismatch with what they said."),
        _tool("prepare_form", "Fill the MassHealth income attestation form (AFVI) PDF. Returns every field to read back to the member."),
        _tool(
            "record_consent",
            "Call right after the member clearly says yes to your consent question. consent_text is the exact question you asked.",
            {"consent_text": {"type": "string"}, "member_reply": {"type": "string"}},
        ),
        _tool(
            "submit_to_masshealth",
            "Send the form to MassHealth (mock). Needs a recorded consent, an up-to-date form, and proof or a signed statement.",
            {"pdf_id": {"type": "string"}, "consent_id": {"type": "string"}},
        ),
        _tool(
            "send_confirmation_sms",
            "Text the member the receipt number and a link to their form. Call right after a successful submit.",
            {"receipt_number": {"type": "string"}, "pdf_id": {"type": "string"}},
        ),
        _tool(
            "set_language",
            "Switch the conversation language when the member uses or asks for another language.",
            {"language": {"type": "string", "description": "BCP-47 code, e.g. en, es, pt, ht"}},
        ),
        _tool(
            "handoff_to_human",
            "For appeals, coverage decisions, complaints, or anything MassHelp can't help with. Returns who to call.",
            {"reason": {"type": "string"}},
        ),
    ]


# ---------------------------------------------------------------- dispatch


async def run_tool(ctx: ToolContext, name: str, tool_input: dict) -> dict:
    start = time.perf_counter()
    services = ctx.services
    try:
        handler = HANDLERS.get(name)
        if handler is None:
            result = {"error": f"unknown tool {name}"}
        else:
            with services.db.session() as s:
                case = s.get(Case, ctx.case_id)
                if name not in NO_IDENTITY_TOOLS and not identity_valid(case, services.settings):
                    result = {"error": "identity_not_verified", "message": "Verify the member's identity first."}
                else:
                    result = await handler(ctx, s, case, tool_input or {})
    except Exception as exc:  # noqa: BLE001 - tool errors go back to the model, never crash the turn
        log.exception("tool %s failed", name)
        result = {"error": "tool_failed", "message": str(exc)[:300]}
    with services.db.session() as s:
        log_event(s, ctx.case_id, "tool_call", {
            "tool": name, "input": tool_input, "ms": round((time.perf_counter() - start) * 1000),
            "ok": "error" not in result, "result": result if len(json.dumps(result, default=str)) < 2000 else "(large)",
        })
    return redact_obj(result)


# ---------------------------------------------------------------- helpers


def run_evaluation(services, s: Session, case: Case, month: str | None = None) -> Evaluation:
    member = case_member(s, case)
    answers = latest_answers(s, case.id)
    month_str = month or (answers["month"].value if "month" in answers else None) or case.verify_month
    ym = YearMonth.parse(month_str) if month_str else YearMonth.from_date(today()).previous()
    evaluation = evaluate(facts_from_answers(answers, member, ym), ym, services.rules)
    if month is None or month == case.verify_month:
        case.last_evaluation_json = evaluation.model_dump_json()
        s.add(case)
        s.commit()
    return evaluation


def evaluation_view(services, s: Session, case: Case, ev: Evaluation) -> dict:
    rules = services.rules
    out: dict[str, Any] = {
        "status": ev.status.value,
        "path": ev.path,
        "other_paths_met": ev.other_paths_met,
        "reasons": ev.reasons,
        "missing": ev.missing,
        "notes": ev.notes,
    }
    if ev.proof_needed:
        from masshelp.forms.build import current_proof

        answers = latest_answers(s, case.id)
        proof = current_proof(s, case, ev, answers)
        out["proof_needed"] = [
            {"covers": n["covers"], "any_of": [{"id": o, "label": rules.proof_types[o].label} for o in n["any_of"]]}
            for n in ev.proof_needed
        ]
        out["proof_status"] = {
            "complete": proof["complete"],
            "covered": proof["covered"],
            "waiting_for": [n["covers"] for n in proof["waiting_for"]],
            "attestation": proof["attestation"],
        }
    if ev.status in (Status.LIKELY_MEETS, Status.LIKELY_EXEMPT):
        supported, note = form_support(ev)
        out["form_supported"] = supported
        if note:
            out["form_note"] = note
    if ev.status == Status.LIKELY_DOES_NOT_MEET:
        c = rules.contacts
        out["next_steps"] = {
            "say": "Explain honestly and kindly. Ask if another month or another way (school, volunteering, training) could work. "
                   "If not, give the MassHealth number and suggest the Health Connector.",
            "masshealth_phone": c["masshealth_customer_service"],
            "health_connector_phone": c["health_connector"],
            "health_connector_url": c["health_connector_url"],
        }
    return out


def _lang(case: Case) -> str:
    return base_language(case.language)


_NEGATIVE = re.compile(r"\b(no|not|don'?t|do not|never|wait|stop|nope|espera|todav[ií]a no|no quiero)\b")
_AFFIRMATIVE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|agree|i agree|correct|go ahead|do it|please do|submit|send it|that's right|"
    r"s[ií]|claro|de acuerdo|est[aá] bien|adelante|dale|acepto|env[ií]elo|correcto)\b"
)


def is_affirmative(reply: str) -> bool:
    text = (reply or "").lower().strip()
    text = re.sub(r"[^\w\s'áéíóúñü]", " ", text)
    words = text.split()
    if not words:
        return False
    if _NEGATIVE.match(text):
        return False
    starts_yes = bool(_AFFIRMATIVE.match(text))
    if not starts_yes and _NEGATIVE.search(text):
        return False
    return bool(_AFFIRMATIVE.search(text))


# ---------------------------------------------------------------- handlers


async def verify_identity(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    services = ctx.services
    settings = services.settings
    if identity_valid(case, settings):
        return {"verified": True, "already_verified": True}
    if identity_locked(case, settings):
        return {"verified": False, "locked": True, "attempts_left": 0,
                "say": t("identity_locked", case.language, phone=services.rules.contacts["masshealth_customer_service"])}
    masshealth = services.masshealth
    dob = parse_date(inp.get("date_of_birth") or "")
    mh_id = (inp.get("masshealth_id") or "").strip()
    candidate = masshealth.get_member_by_phone(case.phone_e164)
    if candidate is None:
        if not mh_id:
            return {"verified": False, "need": "masshealth_id",
                    "message": "This phone number is not on file. Ask for the MassHealth ID and date of birth.",
                    "attempts_left": settings.max_identity_attempts - case.identity_attempts}
        candidate = masshealth.get_member_by_id(mh_id)
    if dob is None:
        return {"verified": False, "need": "date_of_birth", "message": "Ask for the full date of birth (month, day, year).",
                "attempts_left": settings.max_identity_attempts - case.identity_attempts}

    if candidate is None or candidate.dob != dob:
        case.identity_attempts += 1
        s.add(case)
        s.commit()
        left = max(settings.max_identity_attempts - case.identity_attempts, 0)
        log_event(s, case.id, "identity_failed", {"attempts": case.identity_attempts})
        result: dict[str, Any] = {"verified": False, "attempts_left": left}
        if left == 0:
            result["locked"] = True
            result["say"] = t("identity_locked", case.language, phone=services.rules.contacts["masshealth_customer_service"])
        else:
            result["message"] = "That didn't match. Ask them to check and try again. Don't say which part was wrong."
        return result

    case.member_id = candidate.id
    case.identity_verified = True
    case.identity_verified_at = utcnow()
    case.identity_attempts = 0
    if case.status in (CaseStatus.IDENTITY_PENDING, CaseStatus.OPEN):
        case.status = CaseStatus.IN_PROGRESS
    requests = masshealth.get_open_requests(candidate.id)
    if requests:
        req = requests[0]
        case.request_id, case.request_type = req.id, req.request_type
        case.verify_month, case.deadline = req.verify_month, req.deadline
    s.add(case)
    s.commit()
    log_event(s, case.id, "identity_verified", {"member_id": candidate.id})
    return {"verified": True, "first_name": candidate.first_name,
            "preferred_language": candidate.preferred_language, "next": "Call get_case_status."}


async def get_case_status(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    member = case_member(s, case)
    answers = latest_answers(s, case.id)
    ev = run_evaluation(ctx.services, s, case)
    month = YearMonth.parse(case.verify_month) if case.verify_month else None
    submission = s.exec(select(Submission).where(Submission.case_id == case.id)).first()
    docs = case_documents(s, case.id)
    return {
        "first_name": member.first_name if member else None,
        "language": case.language,
        "preferred_language": member.preferred_language if member else None,
        "request": {
            "type": case.request_type,
            "month": case.verify_month,
            "month_name": month.first_day.strftime("%B %Y") if month else None,
            "deadline": case.deadline.isoformat() if case.deadline else None,
        } if case.request_type else None,
        "today": today().isoformat(),
        "answers": answers_for_display(answers),
        "documents_received": len(docs),
        "evaluation": evaluation_view(ctx.services, s, case, ev),
        "submitted": {"receipt_number": submission.receipt_number} if submission else None,
    }


async def record_answers(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    rules = ctx.services.rules
    saved, errors = [], []
    for item in inp.get("answers") or []:
        field, raw = item.get("field"), item.get("value")
        try:
            value = parse_value(field, raw, rules)
        except AnswerError as exc:
            errors.append({"field": field, "error": str(exc)})
            continue
        if isinstance(value, str):
            value = redact(value)
        save_answer(s, case.id, field, value, ctx.channel, message_id=ctx.user_message_id)
        saved.append(field)
    s.commit()
    recon = refresh_reconciliation(ctx.services, s, case)
    s.commit()
    ev = run_evaluation(ctx.services, s, case)
    out: dict[str, Any] = {"saved": saved, "answers": answers_for_display(latest_answers(s, case.id)),
                           "evaluation": evaluation_view(ctx.services, s, case, ev)}
    if errors:
        out["errors"] = errors
    if recon["mismatch"]:
        out["document_mismatch"] = recon["comparison"]
    return out


async def evaluate_requirement(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    month = inp.get("month")
    if month:
        try:
            month = str(YearMonth.parse(month))
        except (ValueError, IndexError):
            return {"error": "month must be YYYY-MM"}
    ev = run_evaluation(ctx.services, s, case, month)
    return evaluation_view(ctx.services, s, case, ev)


async def request_document(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    rules = ctx.services.rules
    doc_type = inp.get("doc_type")
    pt = rules.proof_types.get(doc_type)
    if pt is None:
        return {"error": f"doc_type must be one of {list(rules.proof_types)}"}
    lang = _lang(case)
    instructions = pt.instructions.get(lang) or pt.instructions["en"]
    alternatives = [{"id": a, "label": rules.proof_types[a].label} for a in pt.alternatives]
    if ctx.channel == "voice":
        body = t("sms_prefix", lang) + t("document_request", lang, instructions=instructions)
        sent = await send_case_sms(ctx.services.messenger, s, case, body,
                                   limit=ctx.services.settings.sms_split_chars, kind="document_request")
        return {"sms_sent": sent, "instructions_texted": instructions, "alternatives": alternatives,
                "say": "Tell the member you just texted them what to send." if sent else
                       "Texting is not available. Don't say you texted. In one sentence, say what proof works. "
                       "Then offer to send the form now with a signed statement instead "
                       "(record attestation_accepted=true if they agree)."}
    return {"sms_sent": False, "instructions": instructions, "alternatives": alternatives,
            "say": "You are texting already: put these instructions in your reply (in the member's language)."}


async def get_documents(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    recon = refresh_reconciliation(ctx.services, s, case)
    s.commit()
    docs = []
    for d in case_documents(s, case.id):
        ex = json.loads(d.extracted_json)
        docs.append({
            "id": d.id, "readable": d.readable, "doc_type": d.doc_type, "mismatch": d.mismatch_flag,
            "unreadable_reason": ex.get("unreadable_reason"),
            "employer_or_platform": ex.get("employer_or_platform"),
            "period": [ex.get("period_start"), ex.get("period_end")],
            "gross_amount": ex.get("gross_amount"), "net_amount": ex.get("net_amount"), "hours": ex.get("hours"),
            "monthly_estimate": json.loads(d.derived_json),
        })
    return {"documents": docs, "combined_estimate": recon["estimate"], "comparison": recon["comparison"],
            "mismatch": recon["mismatch"]}


async def prepare_form(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    ev = run_evaluation(ctx.services, s, case)
    supported, note = form_support(ev)
    if not supported:
        return {"error": "form_not_supported", "status": ev.status.value, "message": note,
                "masshealth_phone": ctx.services.rules.contacts["masshealth_customer_service"]}
    member = case_member(s, case)
    built = build_form(ctx.services, s, case, member, ev)
    pdf = write_pdf(ctx.services, s, case, built, kind="draft")
    if built.proof["complete"]:
        case.status = CaseStatus.READY_TO_SUBMIT
        s.add(case)
        s.commit()
    return {
        "pdf_id": pdf.id,
        "form": "Attestation Form to Verify Income (AFVI), filled in English",
        "fields": built.read_back,
        "proof_complete": built.proof["complete"],
        "next": "Read these fields back in plain language (in the member's language), ask them to confirm or correct, "
                "then ask the consent question.",
    }


def _latest_draft(s: Session, case_id: str) -> FormPdf | None:
    return s.exec(select(FormPdf).where(FormPdf.case_id == case_id, FormPdf.kind == "draft")
                  .order_by(col(FormPdf.created_at).desc())).first()


async def record_consent(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    pdf = _latest_draft(s, case.id)
    if pdf is None:
        return {"error": "no_form", "message": "Call prepare_form and read it back first."}
    actual = ctx.user_text or ""
    if not is_affirmative(actual):
        return {"error": "not_a_clear_yes",
                "message": "The member's last message is not a clear yes. Ask the consent question again."}
    consent = Consent(case_id=case.id, consent_text=redact(inp.get("consent_text") or "")[:1000],
                      member_reply=actual[:500], channel=ctx.channel, pdf_id=pdf.id, facts_hash=pdf.facts_hash)
    s.add(consent)
    s.commit()
    log_event(s, case.id, "consent_recorded", {"consent_id": consent.id, "pdf_id": pdf.id})
    return {"consent_id": consent.id, "pdf_id": pdf.id, "next": "Call submit_to_masshealth with these ids."}


async def submit_to_masshealth(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    services = ctx.services
    existing = s.exec(select(Submission).where(Submission.case_id == case.id)).first()
    if existing:
        return {"already_submitted": True, "receipt_number": existing.receipt_number, "pdf_id": existing.pdf_id}
    consent = s.get(Consent, inp.get("consent_id") or "")
    pdf = s.get(FormPdf, inp.get("pdf_id") or "")
    if consent is None or consent.case_id != case.id:
        return {"error": "no_consent", "message": "Ask the consent question and call record_consent first."}
    if pdf is None or pdf.case_id != case.id or consent.pdf_id != pdf.id:
        return {"error": "wrong_pdf", "message": "Use the pdf_id returned by record_consent."}

    ev = run_evaluation(services, s, case)
    supported, note = form_support(ev)
    if not supported:
        return {"error": "form_not_supported", "message": note}
    member = case_member(s, case)
    built = build_form(services, s, case, member, ev)
    if built.facts_hash != consent.facts_hash:
        return {"error": "form_changed",
                "message": "Answers changed after consent. Call prepare_form, read back what changed, and ask for consent again."}
    if not built.proof["complete"]:
        rules = services.rules
        return {
            "error": "waiting_for_proof",
            "waiting_for": [[rules.proof_types[o].label for o in n["any_of"]] for n in built.proof["waiting_for"]],
            "message": "Proof hasn't arrived yet. Tell the member you'll submit as soon as their photo arrives by text. "
                       "If they can't get it, they can choose a signed statement instead: record attestation_accepted=true, "
                       "then submit again with the same ids.",
        }

    packet = {"request_id": case.request_id, "form": "AFVI_2025-10", "month": case.verify_month,
              "fields": built.read_back, "evaluation": ev.model_dump(mode="json"), "consent_id": consent.id,
              "documents": built.proof["documents"]}
    receipt = services.masshealth.submit_verification(member.id, packet)
    stamp = FinalStamp(
        signer_name=f"{member.first_name} {member.last_name}", channel=consent.channel, consent_id=consent.id,
        consented_at=consent.created_at.strftime("%m/%d/%Y %H:%M UTC"), signature_date=us_date(today()),
        receipt_number=receipt.receipt_number,
    )
    final = write_pdf(services, s, case, built, kind="final", stamp=stamp)
    s.add(Submission(case_id=case.id, pdf_id=final.id, pdf_path=final.path, consent_id=consent.id,
                     receipt_number=receipt.receipt_number, packet_json=json.dumps(redact_obj(packet), default=str)))
    case.status = CaseStatus.SUBMITTED
    s.add(case)
    s.commit()
    log_event(s, case.id, "submitted", {"receipt": receipt.receipt_number})
    return {"receipt_number": receipt.receipt_number, "submitted_at": receipt.submitted_at, "pdf_id": final.id,
            "next": "Call send_confirmation_sms, then tell the member it was sent and MassHealth makes the final decision."}


async def send_confirmation_sms(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    services = ctx.services
    sub = s.exec(select(Submission).where(Submission.case_id == case.id,
                                          Submission.receipt_number == (inp.get("receipt_number") or ""))).first()
    if sub is None:
        return {"error": "unknown_receipt"}
    pdf = s.get(FormPdf, sub.pdf_id)
    link = file_url(services, pdf)
    body = t("confirmation", case.language, receipt=sub.receipt_number, link=link,
             phone=services.rules.contacts["masshealth_customer_service"])
    media = [link] if services.settings.twilio_send_pdf_media else None
    sent = await send_case_sms(services.messenger, s, case, body, media_urls=media,
                               limit=services.settings.sms_split_chars, kind="confirmation")
    out = {"sent": sent, "link": link}
    if not sent:
        out["say"] = ("Texting is not available. Don't say you texted. Read the receipt number aloud slowly, "
                      "one character at a time, and say MassHealth makes the final decision.")
    return out


async def set_language(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    lang = (inp.get("language") or "en").strip()[:12]
    case.language = lang
    s.add(case)
    s.commit()
    return {"ok": True, "language": lang}


async def handoff_to_human(ctx: ToolContext, s: Session, case: Case, inp: dict) -> dict:
    c = ctx.services.rules.contacts
    log_event(s, case.id, "handoff", {"reason": inp.get("reason")})
    return {"phone": c["masshealth_customer_service"], "health_connector_phone": c["health_connector"],
            "message": "Give the MassHealth number. For appeals, they can also ask a local legal aid office."}


HANDLERS = {
    "verify_identity": verify_identity,
    "get_case_status": get_case_status,
    "record_answers": record_answers,
    "evaluate_requirement": evaluate_requirement,
    "request_document": request_document,
    "get_documents": get_documents,
    "prepare_form": prepare_form,
    "record_consent": record_consent,
    "submit_to_masshealth": submit_to_masshealth,
    "send_confirmation_sms": send_confirmation_sms,
    "set_language": set_language,
    "handoff_to_human": handoff_to_human,
}
