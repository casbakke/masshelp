"""Structured answer fields (SPEC 6.3): types, parsing, labels, and the facts builder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from masshelp.rules.models import EmploymentType, MemberFacts, RulesConfig, SchoolEnrollment, YearMonth
from masshelp.store.models import Answer, Member
from masshelp.util.dates import age_on

BOOL_FIELDS = {"is_exempt_claimed", "is_seasonal", "health_insurance_offered", "attestation_accepted"}
NUMBER_FIELDS = {
    "weekly_hours",
    "monthly_hours",
    "monthly_gross_income",
    "monthly_expenses",
    "monthly_net_income",
    "seasonal_average_monthly_income",
    "volunteer_hours",
    "training_hours",
    "expected_annual_income",
}
TEXT_FIELDS = {"employer_or_platform", "school_name", "volunteer_org", "training_program"}
ENUM_FIELDS = {
    "employment_type": [e.value for e in EmploymentType],
    "school_enrollment": [e.value for e in SchoolEnrollment],
    # exemption_type values come from the rules config
}
MONTH_FIELDS = {"month"}

ANSWER_FIELDS = [
    "month",
    "is_exempt_claimed",
    "exemption_type",
    "employment_type",
    "employer_or_platform",
    "weekly_hours",
    "monthly_hours",
    "monthly_gross_income",
    "monthly_expenses",
    "monthly_net_income",
    "is_seasonal",
    "seasonal_average_monthly_income",
    "school_name",
    "school_enrollment",
    "volunteer_org",
    "volunteer_hours",
    "training_program",
    "training_hours",
    "health_insurance_offered",
    "expected_annual_income",
    "attestation_accepted",
]

FIELD_LABELS = {
    "month": "Month being verified",
    "is_exempt_claimed": "Claims an exemption",
    "exemption_type": "Exemption",
    "employment_type": "Type of work",
    "employer_or_platform": "Employer or app",
    "weekly_hours": "Hours per week",
    "monthly_hours": "Hours in the month",
    "monthly_gross_income": "Monthly earnings before costs",
    "monthly_expenses": "Monthly work costs (gas, mileage)",
    "monthly_net_income": "Monthly earnings after work costs",
    "is_seasonal": "Seasonal worker",
    "seasonal_average_monthly_income": "Average monthly income, last 6 months",
    "school_name": "School",
    "school_enrollment": "School enrollment",
    "volunteer_org": "Volunteer organization",
    "volunteer_hours": "Volunteer hours in the month",
    "training_program": "Job training program",
    "training_hours": "Job training hours in the month",
    "health_insurance_offered": "Employer offers health insurance",
    "expected_annual_income": "Expected yearly income",
    "attestation_accepted": "Signed statement instead of papers",
}

FIELD_HELP = {
    "monthly_gross_income": "Earnings for the month before work costs. For employees: wages before taxes.",
    "monthly_net_income": "Self-employed or gig only: earnings after business costs like gas. Never take-home pay after taxes.",
    "monthly_expenses": "Self-employed or gig only: business costs for the month (gas, mileage, supplies).",
    "weekly_hours": "Usual work hours per week. Converted to monthly as weekly x 4.33, rounded down.",
    "is_exempt_claimed": "true if any exemption likely applies; false only after the member said no to the screening questions.",
}

_TRUE = {"true", "yes", "y", "si", "sí", "1", "yeah", "yep", "correct"}
_FALSE = {"false", "no", "n", "0", "nope"}


class AnswerError(ValueError):
    pass


def parse_value(field: str, raw: str, rules: RulesConfig) -> object:
    """Convert the model's string value into a typed value. Raises AnswerError."""
    if field not in ANSWER_FIELDS:
        raise AnswerError(f"unknown field {field}")
    value = (raw or "").strip()
    if field in BOOL_FIELDS:
        low = value.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise AnswerError(f"{field} needs true or false, got {raw!r}")
    if field in NUMBER_FIELDS:
        cleaned = re.sub(r"[,$\s]|about|around|approx\.?|aprox\.?|usd", "", value.lower())
        try:
            number = float(cleaned)
        except ValueError as exc:
            raise AnswerError(f"{field} needs a number, got {raw!r}") from exc
        if number < 0:
            raise AnswerError(f"{field} can't be negative")
        return number
    if field in MONTH_FIELDS:
        try:
            return str(YearMonth.parse(value))
        except (ValueError, IndexError) as exc:
            raise AnswerError(f"{field} needs YYYY-MM, got {raw!r}") from exc
    if field == "exemption_type":
        if value not in rules.exemption_ids:
            raise AnswerError(f"exemption_type must be one of {rules.exemption_ids}")
        return value
    if field in ENUM_FIELDS:
        if value not in ENUM_FIELDS[field]:
            raise AnswerError(f"{field} must be one of {ENUM_FIELDS[field]}")
        return value
    if not value:
        raise AnswerError(f"{field} can't be empty")
    return value[:200]


@dataclass
class AnswerView:
    value: object
    source: str
    created_at: datetime
    document_id: str | None = None


def latest_answers(session: Session, case_id: str) -> dict[str, AnswerView]:
    """Latest value per field (history is kept in the table)."""
    rows = session.exec(select(Answer).where(Answer.case_id == case_id).order_by(Answer.id)).all()
    out: dict[str, AnswerView] = {}
    for row in rows:
        out[row.field] = AnswerView(
            value=json.loads(row.value_json), source=row.source, created_at=row.created_at,
            document_id=row.document_id,
        )
    return out


def save_answer(
    session: Session,
    case_id: str,
    field: str,
    value: object,
    source: str,
    message_id: int | None = None,
    document_id: str | None = None,
) -> None:
    session.add(
        Answer(
            case_id=case_id,
            field=field,
            value_json=json.dumps(value),
            source=source,
            message_id=message_id,
            document_id=document_id,
        )
    )


def facts_from_answers(
    answers: dict[str, AnswerView], member: Member | None, month: YearMonth
) -> MemberFacts:
    values = {k: v.value for k, v in answers.items()}
    data: dict[str, object] = {
        k: values.get(k)
        for k in MemberFacts.model_fields
        if k not in ("age", "program") and values.get(k) is not None
    }
    if member is not None:
        data["age"] = age_on(member.dob, month.first_day)
        data["program"] = member.program
    return MemberFacts.model_validate(data)


def answers_for_display(answers: dict[str, AnswerView]) -> dict[str, dict]:
    return {
        field: {"value": view.value, "source": view.source}
        for field, view in answers.items()
    }
