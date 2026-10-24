"""Demo scenarios 9.1 and 9.2 with a scripted fake LLM. The fake decides what to say
and which tools to call; everything else (tools, rules engine, documents, PDF,
consent, mock submission, SMS) is the real code.
"""

from __future__ import annotations

import json

from pypdf import PdfReader
from sqlmodel import select

from masshelp.agent.llm import LLMResult, text_block, tool_block
from masshelp.docs.ingest import IncomingMedia
from masshelp.store.models import Case, Consent, Message, Submission
from tests.conftest import CARLOS, MARIA, UNKNOWN
from tests.conversations.helpers import open_case, say

def _tiny_png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="PNG")
    return buf.getvalue()


PNG = _tiny_png()  # content doesn't matter: the fake LLM does the extraction


def result_of(llm, index: int = -1) -> dict:
    """The tool result inside the request the fake LLM received."""
    msgs = llm.calls[index]["messages"]
    for block in msgs[-1]["content"]:
        if block["type"] == "tool_result":
            return json.loads(block["content"])
    raise AssertionError("no tool result")


def ids_from(store: dict):
    return lambda req: store.update(json.loads(req["messages"][-1]["content"][0]["content"])) or [
        text_block("ok")]


async def test_maria_voice_gig_worker(services, llm, messenger):
    case_id = open_case(services, MARIA)

    # 1-2. Identity by DOB (phone on file).
    llm.add([text_block("Thanks. "), tool_block("verify_identity", date_of_birth="1992-06-04", masshealth_id=None)],
            [tool_block("get_case_status")],
            [text_block("Thanks, Maria. There's a new work rule starting January first. I can help you answer it now.")])
    out = await say(services, case_id, "voice", "June fourth, 1992")
    assert "Maria" in out
    status = result_of(llm)
    assert status["request"]["month"] == "2026-11"
    assert status["request"]["deadline"] == "2026-12-31"

    # 4-5. Exemptions no, then income.
    llm.add([tool_block("record_answers", answers=[
                {"field": "is_exempt_claimed", "value": "false"},
                {"field": "employment_type", "value": "gig"},
                {"field": "employer_or_platform", "value": "RouteRunner (food delivery app)"},
                {"field": "weekly_hours", "value": "25"},
                {"field": "monthly_gross_income", "value": "1150"},
                {"field": "monthly_net_income", "value": "900"},
            ])],
            [text_block("That likely meets the rule. MassHealth makes the final decision.")])
    await say(services, case_id, "voice", "No to all. I drive for a delivery app, 25 hours a week, 1150 before gas, 900 after.")
    ev = result_of(llm)["evaluation"]
    assert ev["status"] == "LIKELY_MEETS" and ev["path"] == "income"
    assert ev["form_supported"] is True
    assert ev["proof_status"]["complete"] is False

    # 6. No pay stubs: text her what to send (R24).
    llm.add([text_block("That's fine. One second while I text you what to send."),
             tool_block("request_document", doc_type="gig_earnings_screenshot")],
            [text_block("I just texted you.")])
    await say(services, case_id, "voice", "I don't have pay stubs.")
    assert result_of(llm)["sms_sent"] is True
    assert "screenshot" in messenger.sent[-1].body and "not MassHealth" in messenger.sent[-1].body

    # 7. Prepare, read back, consent.
    llm.add([text_block("One second."), tool_block("prepare_form")], [text_block("Here's your form...")])
    await say(services, case_id, "voice", "Okay")
    form = result_of(llm)
    assert form["fields"]["Monthly income after costs"] == "$900.00"
    assert form["fields"]["Reason for this form"] == "Documents for this income do not exist"
    pdf_id = form["pdf_id"]

    store: dict = {}
    llm.add([tool_block("record_consent", consent_text="Do you want me to send this form to MassHealth for you?",
                        member_reply="yes")],
            ids_from(store))
    await say(services, case_id, "voice", "Yes, please send it.")
    consent_id = store["consent_id"]

    # 8. Submit waits for the screenshot.
    llm.add([tool_block("submit_to_masshealth", pdf_id=pdf_id, consent_id=consent_id)],
            [text_block("I'll send it as soon as your screenshot arrives.")])
    await say(services, case_id, "voice", "Great")
    assert result_of(llm)["error"] == "waiting_for_proof"

    # Screenshot arrives by text (G3: same case).
    llm.extractions.append({
        "readable": True, "unreadable_reason": None, "doc_type": "gig_earnings_summary", "person_name": "Maria S.",
        "employer_or_platform": "RouteRunner", "period_start": "2026-11-01", "period_end": "2026-11-30",
        "pay_frequency": None, "gross_amount": 1162.40, "net_amount": None, "hours": 104, "notes": None,
    })
    submitted: dict = {}
    llm.add(
        lambda req: [tool_block("submit_to_masshealth", pdf_id=pdf_id, consent_id=consent_id)],
        lambda req: submitted.update(json.loads(req["messages"][-1]["content"][0]["content"])) or [
            tool_block("send_confirmation_sms", receipt_number=submitted["receipt_number"], pdf_id=submitted["pdf_id"])],
        [text_block("Got it, the amount matches. Your form was sent.")],
    )
    case_id_sms = open_case(services, MARIA)
    assert case_id_sms == case_id
    await say(services, case_id, "sms", "", media=[IncomingMedia(PNG, "image/png")])
    note = llm.calls[-3]["messages"][-1]["content"][-1]["text"]
    assert "Matches what the member said" in note
    assert submitted["receipt_number"].startswith("MOCK-RCPT-")

    # 9. Confirmation text with receipt and link.
    confirmation = messenger.sent[-1].body
    assert submitted["receipt_number"] in confirmation and "https://masshelp.test/files/" in confirmation
    with services.db.session() as s:
        sub = s.exec(select(Submission).where(Submission.case_id == case_id)).one()
        consent = s.get(Consent, consent_id)
        assert consent.member_reply.lower().startswith("yes")
        text = "".join(p.extract_text() for p in PdfReader(sub.pdf_path).pages)
        assert "Maria Santos" in text and "MH-DEMO-000123" in text and "SAMPLE - NOT FOR SUBMISSION" in text
        assert s.get(Case, case_id).status == "submitted"


async def test_carlos_sms_spanish_paystubs(services, llm, messenger):
    case_id = open_case(services, CARLOS, "Hola")
    llm.add([text_block("¿Me puede dar su fecha de nacimiento?")])
    out = await say(services, case_id, "sms", "Hola")
    assert out.startswith("Le habla MassHelp. Soy un asistente automático")  # R32 in Spanish (R10)

    llm.add([tool_block("verify_identity", date_of_birth="1985-03-17", masshealth_id=None)],
            [tool_block("record_answers", answers=[
                {"field": "is_exempt_claimed", "value": "false"},
                {"field": "employment_type", "value": "employee"},
            ])],
            [text_block("Gracias. Por favor envíe fotos de sus 2 talones de pago.")])
    out = await say(services, case_id, "sms", "17/03/1985. No a todo. Trabajo tiempo completo en jardinería.")
    assert "Le habla" not in out  # disclosure only once per conversation

    stub = {"readable": True, "unreadable_reason": None, "doc_type": "pay_stub", "person_name": "Carlos Rivera",
            "employer_or_platform": "Green Valley Landscaping LLC", "pay_frequency": "biweekly",
            "gross_amount": 1320.0, "net_amount": 1105.0, "hours": 80, "notes": None}
    llm.extractions += [{**stub, "period_start": "2026-11-01", "period_end": "2026-11-14"},
                        {**stub, "period_start": "2026-11-15", "period_end": "2026-11-28"}]
    llm.add([tool_block("evaluate_requirement", month=None)], [text_block("Recibí sus talones.")])
    await say(services, case_id, "sms", "", media=[IncomingMedia(PNG, "image/png"), IncomingMedia(PNG, "image/jpeg")])
    ev = result_of(llm)
    assert ev["status"] == "LIKELY_MEETS" and ev["proof_status"]["complete"] is True

    llm.add([tool_block("prepare_form")], [text_block("Resumen...")])
    await say(services, case_id, "sms", "ok")
    form = result_of(llm)
    assert form["fields"]["Employer or app"] == "Green Valley Landscaping LLC"
    assert form["proof_complete"] is True

    store: dict = {}
    llm.add([tool_block("record_consent", consent_text="¿Quiere que envíe este formulario a MassHealth?", member_reply="Sí")],
            lambda req: store.update(json.loads(req["messages"][-1]["content"][0]["content"])) or [
                tool_block("submit_to_masshealth", pdf_id=store["pdf_id"], consent_id=store["consent_id"])],
            lambda req: store.update(json.loads(req["messages"][-1]["content"][0]["content"])) or [
                tool_block("send_confirmation_sms", receipt_number=store["receipt_number"], pdf_id=store["pdf_id"])],
            [text_block("Listo.")])
    await say(services, case_id, "sms", "Sí")
    assert store["receipt_number"].startswith("MOCK-RCPT-")
    assert "Número de recibo" in messenger.sent[-1].body  # confirmation in Spanish (R11)


async def test_identity_lockout_after_three(services, llm):
    case_id = open_case(services, MARIA)
    for _ in range(3):
        llm.add([tool_block("verify_identity", date_of_birth="1990-01-01", masshealth_id=None)], [text_block("No match.")])
        await say(services, case_id, "voice", "January first 1990")
    assert result_of(llm)["locked"] is True
    out = await say(services, case_id, "voice", "try again")  # no LLM call needed
    assert "1-800-841-2900" in out


async def test_unknown_number_needs_id(services, llm):
    case_id = open_case(services, UNKNOWN)
    llm.add([tool_block("verify_identity", date_of_birth="1992-06-04", masshealth_id=None)], [text_block("ID?")],
            [tool_block("verify_identity", date_of_birth="1992-06-04", masshealth_id="mh-demo-000123")], [text_block("ok")])
    await say(services, case_id, "sms", "6/4/1992")
    assert result_of(llm)["need"] == "masshealth_id"
    await say(services, case_id, "sms", "MH-DEMO-000123")
    assert result_of(llm)["verified"] is True


async def test_tools_refuse_before_identity(services, llm):
    case_id = open_case(services, MARIA)
    llm.add([tool_block("get_case_status")], [text_block("Please give your date of birth.")])
    await say(services, case_id, "sms", "what's my case")
    assert result_of(llm)["error"] == "identity_not_verified"


async def test_ssn_redacted_and_flagged(services, llm):
    case_id = open_case(services, MARIA)
    llm.add([text_block("You don't need to share that.")])
    await say(services, case_id, "sms", "my ssn is 123-45-6789")
    sent = llm.calls[-1]["messages"][-1]["content"][0]["text"]
    assert "123-45-6789" not in sent and "never needs it" in sent
    with services.db.session() as s:
        for m in s.exec(select(Message).where(Message.case_id == case_id)):
            assert "123-45-6789" not in m.content_json


async def test_refusal_and_error_fallback(services, llm):
    case_id = open_case(services, MARIA)
    llm.add(LLMResult(content=[], stop_reason="refusal"), RuntimeError("boom") if False else _api_error())
    assert "trouble" in await say(services, case_id, "sms", "hi")
    assert "trouble" in await say(services, case_id, "sms", "hi again")


async def test_consent_requires_clear_yes(services, llm):
    from masshelp.agent.tools import is_affirmative

    assert is_affirmative("Yes, please send it.")
    assert is_affirmative("Sí")
    assert is_affirmative("yes, no changes")
    assert not is_affirmative("No, wait")
    assert not is_affirmative("I don't want that")
    assert not is_affirmative("maybe later")


def _api_error():
    from masshelp.agent.llm import LLMError

    return LLMError("simulated outage")
