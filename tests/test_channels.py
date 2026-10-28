"""Twilio and Vapi adapter tests."""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from masshelp.agent.llm import text_block, tool_block
from masshelp.main import create_app
from masshelp.store.models import Case
from tests.conftest import MARIA


def client(services) -> TestClient:
    return TestClient(create_app(services))


def test_sms_returns_empty_twiml_and_replies(services, llm, messenger):
    llm.add([text_block("What's your date of birth?")])
    with client(services) as c:
        r = c.post("/twilio/sms", data={"From": MARIA, "Body": "Hi", "NumMedia": "0"})
    assert r.status_code == 200 and r.text.endswith("<Response/>")
    assert messenger.sent[-1].body.startswith("MassHelp here. I'm a free automated assistant, not MassHealth.")


def test_sms_signature_validation(services):
    services.settings.twilio_validate = True
    services.settings.twilio_auth_token = "test-token"
    params = {"From": MARIA, "Body": "STOP", "NumMedia": "0"}
    url = "https://masshelp.test/twilio/sms"
    good = RequestValidator("test-token").compute_signature(url, params)
    with client(services) as c:
        assert c.post("/twilio/sms", data=params, headers={"X-Twilio-Signature": "bad"}).status_code == 403
        assert c.post("/twilio/sms", data=params, headers={"X-Twilio-Signature": good}).status_code == 200


def test_stop_opts_out_and_suppresses(services, llm, messenger):
    with client(services) as c:
        c.post("/twilio/sms", data={"From": MARIA, "Body": "STOP", "NumMedia": "0"})
        c.post("/twilio/sms", data={"From": MARIA, "Body": "hello?", "NumMedia": "0"})
    assert messenger.sent == []
    assert llm.calls == []


@respx.mock
def test_sms_media_download(services, llm, messenger):
    services.settings.twilio_account_sid = "AC123"
    services.settings.twilio_auth_token = "tok"
    route = respx.get("https://api.twilio.com/media/1").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 fake", headers={"content-type": "application/pdf"}))
    llm.add([text_block("Thanks for the file.")])
    with client(services) as c:
        c.post("/twilio/sms", data={"From": MARIA, "Body": "", "NumMedia": "1",
                                    "MediaUrl0": "https://api.twilio.com/media/1", "MediaContentType0": "application/pdf"})
    assert route.called
    assert route.calls[0].request.headers["authorization"].startswith("Basic ")
    assert "sent 1 file" in llm.calls[-1]["messages"][-1]["content"][0]["text"]


def _sse_events(text: str) -> list:
    return [line.removeprefix("data: ") for line in text.splitlines() if line.startswith("data: ")]


def test_vapi_sse_stream_filler_before_tool(services, llm):
    services.settings.vapi_secret = "s3cret"
    llm.add([text_block("One second while I check that."), tool_block("get_case_status")],
            [text_block("Please tell me your date of birth.")])
    body = {"model": "masshelp", "stream": True, "call": {"id": "call-1", "customer": {"number": MARIA}},
            "messages": [{"role": "assistant", "content": "Hi"}, {"role": "user", "content": "Hello"}]}
    with client(services) as c:
        assert c.post("/vapi/chat/completions", json=body).status_code == 401
        r = c.post("/vapi/chat/completions", json=body, headers={"Authorization": "Bearer s3cret"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(r.text)
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    spoken = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert spoken.startswith("One second while I check that.")
    assert spoken.endswith("Please tell me your date of birth.")
    # The filler streamed before the second model call (which happens after the tool ran).
    assert len(llm.calls) == 2
    from sqlmodel import select

    with services.db.session() as s:
        assert len(s.exec(select(Case).where(Case.last_call_id == "call-1")).all()) == 1


def test_files_link(services, tmp_path):
    from datetime import timedelta

    from masshelp.store.models import FormPdf
    from masshelp.util.dates import utcnow

    pdf_path = tmp_path / "x.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    with services.db.session() as s:
        live = FormPdf(case_id="c", path=str(pdf_path), expires_at=utcnow() + timedelta(days=1))
        dead = FormPdf(case_id="c", path=str(pdf_path), expires_at=utcnow() - timedelta(days=1))
        s.add(live), s.add(dead)
        s.commit()
    with client(services) as c:
        assert c.get(f"/files/{live.token}").status_code == 200
        assert c.get(f"/files/{dead.token}").status_code == 404
        assert c.get("/files/nope").status_code == 404
