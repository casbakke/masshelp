"""Mock MassHealth service behind a swappable interface (SPEC 5.7).

Nothing here talks to MassHealth. Members, requests, and receipts are dummy data
seeded from seed/members.yaml.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import yaml
from sqlmodel import select

from masshelp.config import Settings
from masshelp.store.db import Database
from masshelp.store.models import Member, MockRequest
from masshelp.util.dates import utcnow
from masshelp.util.phone import normalize_phone


@dataclass
class Receipt:
    receipt_number: str
    submitted_at: str


class MassHealthClient(Protocol):
    def get_member_by_phone(self, phone: str) -> Member | None: ...
    def get_member_by_id(self, masshealth_id: str) -> Member | None: ...
    def get_member(self, member_id: str) -> Member | None: ...
    def get_open_requests(self, member_id: str) -> list[MockRequest]: ...
    def submit_verification(self, member_id: str, packet: dict[str, Any]) -> Receipt: ...


class MockMassHealthClient:
    def __init__(self, db: Database):
        self.db = db

    def get_member_by_phone(self, phone: str) -> Member | None:
        phone = normalize_phone(phone) or phone
        with self.db.session() as s:
            return s.exec(select(Member).where(Member.phone_e164 == phone)).first()

    def get_member_by_id(self, masshealth_id: str) -> Member | None:
        key = masshealth_id.strip().upper()
        with self.db.session() as s:
            return s.exec(select(Member).where(Member.masshealth_id == key)).first()

    def get_member(self, member_id: str) -> Member | None:
        with self.db.session() as s:
            return s.get(Member, member_id)

    def get_open_requests(self, member_id: str) -> list[MockRequest]:
        with self.db.session() as s:
            return list(
                s.exec(
                    select(MockRequest)
                    .where(MockRequest.member_id == member_id, MockRequest.status == "open")
                    .order_by(MockRequest.deadline)
                )
            )

    def submit_verification(self, member_id: str, packet: dict[str, Any]) -> Receipt:
        receipt = f"MOCK-RCPT-{secrets.randbelow(90000) + 10000}"
        with self.db.session() as s:
            for req in s.exec(
                select(MockRequest).where(MockRequest.member_id == member_id, MockRequest.status == "open")
            ):
                if packet.get("request_id") in (None, req.id):
                    req.status = "received"
                    s.add(req)
            s.commit()
        return Receipt(receipt_number=receipt, submitted_at=utcnow().isoformat(timespec="seconds") + "Z")


# ---------------------------------------------------------------- seeding


def load_seed(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["members"]


def seed_members(db: Database, settings: Settings, *, reset_requests: bool = True) -> int:
    """Upsert seed members and their open requests. Returns the number of members."""
    rows = load_seed(settings.seed_path)
    with db.session() as s:
        for row in rows:
            phone = row.get("phone_default")
            if row.get("phone_setting"):
                phone = getattr(settings, row["phone_setting"], None) or phone
            member = s.get(Member, row["id"]) or Member(id=row["id"], masshealth_id=row["masshealth_id"],
                                                         first_name=row["first_name"], last_name=row["last_name"],
                                                         dob=_as_date(row["dob"]))
            member.masshealth_id = row["masshealth_id"].upper()
            member.first_name = row["first_name"]
            member.last_name = row["last_name"]
            member.dob = _as_date(row["dob"])
            member.phone_e164 = normalize_phone(phone)
            member.preferred_language = row.get("preferred_language", "en")
            member.program = row.get("program", "CarePlus")
            member.seed_facts_json = json.dumps(row.get("seed_facts", {}))
            s.add(member)

            req = row.get("open_request")
            if req and reset_requests:
                for old in s.exec(select(MockRequest).where(MockRequest.member_id == member.id)):
                    s.delete(old)
                s.add(
                    MockRequest(
                        member_id=member.id,
                        request_type=req.get("type", "work_requirement_verification"),
                        verify_month=str(req["month"]),
                        deadline=_as_date(req["deadline"]),
                    )
                )
        s.commit()
    return len(rows)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))
