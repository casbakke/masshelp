"""SQLModel tables (SPEC 5.9). All timestamps are naive UTC."""

# No `from __future__ import annotations` here: SQLModel needs real annotations.
import json
import secrets
from datetime import date, datetime
from typing import Any

from sqlmodel import Field, SQLModel

from masshelp.util.dates import utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


class CaseStatus:
    OPEN = "open"
    IDENTITY_PENDING = "identity_pending"
    IN_PROGRESS = "in_progress"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    CLOSED = "closed"


class Member(SQLModel, table=True):
    id: str = Field(primary_key=True)
    masshealth_id: str = Field(index=True, unique=True)
    first_name: str
    last_name: str
    dob: date
    phone_e164: str | None = Field(default=None, index=True)
    preferred_language: str = "en"
    program: str = "CarePlus"
    seed_facts_json: str = "{}"


class MockRequest(SQLModel, table=True):
    """What MassHealth (mock) has asked the member for."""

    id: str = Field(default_factory=lambda: new_id("req"), primary_key=True)
    member_id: str = Field(index=True)
    request_type: str = "work_requirement_verification"
    verify_month: str  # YYYY-MM
    deadline: date
    status: str = "open"  # open, received


class Case(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("case"), primary_key=True)
    member_id: str | None = Field(default=None, index=True)
    phone_e164: str = Field(index=True)
    status: str = CaseStatus.IDENTITY_PENDING
    identity_verified: bool = False
    identity_verified_at: datetime | None = None
    identity_attempts: int = 0
    language: str = "en"
    request_id: str | None = None
    request_type: str | None = None
    verify_month: str | None = None
    deadline: date | None = None
    opted_out: bool = False
    last_evaluation_json: str | None = None
    last_sms_out_at: datetime | None = None
    last_call_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    case_id: str = Field(index=True)
    channel: str  # sms, voice
    role: str  # user, assistant
    content_json: str  # full Claude content blocks (redacted)
    redacted_text: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def content(self) -> list[dict[str, Any]]:
        return json.loads(self.content_json)


class Answer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    case_id: str = Field(index=True)
    field: str
    value_json: str
    source: str  # voice, sms, document
    message_id: int | None = None
    document_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("doc"), primary_key=True)
    case_id: str = Field(index=True)
    media_path: str
    content_type: str
    doc_type: str | None = None
    readable: bool = True
    extracted_json: str = "{}"
    derived_json: str = "{}"
    mismatch_flag: bool = False
    mismatch_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)


class FormPdf(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("pdf"), primary_key=True)
    case_id: str = Field(index=True)
    kind: str = "draft"  # draft, final
    path: str
    fields_json: str = "{}"
    facts_hash: str = ""
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(24), index=True, unique=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)


class Consent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("consent"), primary_key=True)
    case_id: str = Field(index=True)
    consent_text: str
    member_reply: str
    channel: str
    pdf_id: str | None = None
    facts_hash: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Submission(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("sub"), primary_key=True)
    case_id: str = Field(index=True)
    pdf_id: str
    pdf_path: str
    consent_id: str
    receipt_number: str = Field(index=True)
    packet_json: str
    created_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    """Audit log: tool calls, refusals, errors, latency, outbound SMS."""

    id: int | None = Field(default=None, primary_key=True)
    case_id: str | None = Field(default=None, index=True)
    type: str = Field(index=True)
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)
