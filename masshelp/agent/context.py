"""Per-turn context block. Goes after the cache breakpoint (SPEC 5.2), so it can change
every turn. Before identity is verified it holds no member data (R6).
"""

from __future__ import annotations

from sqlmodel import Session

from masshelp.answers import latest_answers
from masshelp.cases import case_member, identity_valid, last_evaluation
from masshelp.util.dates import today
from masshelp.util.lang import language_name

VOICE_STYLE = "PHONE CALL: at most 2 short sentences, no lists or links, numbers and dates in words."
SMS_STYLE = "TEXT MESSAGE: short paragraphs, numbered lists OK, under about 600 characters."


def build_context(services, s: Session, case, channel: str, *, sms_disclosure_added: bool) -> str:
    settings = services.settings
    lines = [
        f"Today: {today():%A, %B %-d, %Y}.",
        f"Channel: {VOICE_STYLE if channel == 'voice' else SMS_STYLE}",
        f"Conversation language: {language_name(case.language)} ({case.language}).",
    ]
    if channel == "sms" and sms_disclosure_added:
        lines.append("The disclosure line was added before your reply this turn. Don't repeat it.")
    if not identity_valid(case, settings):
        on_file = services.masshealth.get_member_by_phone(case.phone_e164) is not None
        left = settings.max_identity_attempts - case.identity_attempts
        lines.append("Identity: NOT verified. Do not share any case details.")
        lines.append(
            "Phone number on file: yes. Ask for date of birth." if on_file
            else "Phone number on file: no. Ask for the MassHealth ID and date of birth."
        )
        lines.append(f"Identity attempts left: {left}.")
        return "\n".join(lines)

    member = case_member(s, case)
    lines.append(f"Identity: verified. Member first name: {member.first_name if member else 'unknown'}.")
    if case.request_type:
        lines.append(f"MassHealth asked about: {case.verify_month}, deadline {case.deadline}.")
    answers = latest_answers(s, case.id)
    if answers:
        lines.append("Answers so far: " + "; ".join(f"{k}={v.value} ({v.source})" for k, v in answers.items()))
    ev = last_evaluation(case)
    if ev:
        lines.append(f"Last engine result: {ev.status.value}" + (f" by {ev.path}" if ev.path else ""))
    lines.append(f"Case status: {case.status}.")
    return "\n".join(lines)
