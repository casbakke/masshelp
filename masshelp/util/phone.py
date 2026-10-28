"""Phone number normalization to E.164 (US default)."""

from __future__ import annotations

import re


def normalize_phone(raw: str | None) -> str | None:
    """Normalize a phone number to E.164. Returns None if it can't be parsed.

    Assumes US numbers when no country code is given.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("whatsapp:"):
        raw = raw.removeprefix("whatsapp:")
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if has_plus:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if 8 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def last_four(phone: str | None) -> str:
    return (phone or "")[-4:]
