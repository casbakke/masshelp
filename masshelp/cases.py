"""Case lookup and identity state. One open case per phone number; SMS and voice
from the same number resolve to the same case (G3).
"""

from __future__ import annotations

import json
from datetime import timedelta

from sqlmodel import Session, col, select

from masshelp.config import Settings
from masshelp.masshealth_mock.service import MassHealthClient
from masshelp.rules.models import Evaluation
from masshelp.store.db import log_event
from masshelp.store.models import Case, CaseStatus, Member
from masshelp.util.dates import utcnow
from masshelp.util.lang import guess_language


def find_active_case(session: Session, phone: str) -> Case | None:
    return session.exec(
        select(Case)
        .where(Case.phone_e164 == phone, Case.status != CaseStatus.CLOSED)
        .order_by(col(Case.created_at).desc())
    ).first()


def get_or_create_case(
    session: Session, masshealth: MassHealthClient, phone: str, first_text: str | None = None
) -> Case:
    case = find_active_case(session, phone)
    if case is not None:
        return case
    member = masshealth.get_member_by_phone(phone)
    # R10: start in the language on the member's record. Unknown numbers: guess from text.
    language = member.preferred_language if member else (guess_language(first_text) or "en")
    case = Case(phone_e164=phone, language=language)
    session.add(case)
    session.commit()
    log_event(session, case.id, "case_created", {"phone_on_file": member is not None})
    return case


def identity_valid(case: Case, settings: Settings) -> bool:
    if not case.identity_verified or case.identity_verified_at is None:
        return False
    return utcnow() - case.identity_verified_at < timedelta(hours=settings.identity_ttl_hours)


def identity_locked(case: Case, settings: Settings) -> bool:
    return not identity_valid(case, settings) and case.identity_attempts >= settings.max_identity_attempts


def case_member(session: Session, case: Case) -> Member | None:
    return session.get(Member, case.member_id) if case.member_id else None


def last_evaluation(case: Case) -> Evaluation | None:
    if not case.last_evaluation_json:
        return None
    return Evaluation.model_validate_json(case.last_evaluation_json)


def touch(session: Session, case: Case) -> None:
    case.updated_at = utcnow()
    session.add(case)
    session.commit()


def dumps(obj: object) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)
