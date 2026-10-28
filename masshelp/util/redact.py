"""Redact SSN-like, card-like, and bank-account-like numbers from text (R9, R37).

Redaction runs before anything is stored or sent to the LLM, so the model never
sees these numbers and the transcript never holds them.
"""

from __future__ import annotations

import re
from typing import Any

SSN_TOKEN = "[REDACTED-SSN]"
CARD_TOKEN = "[REDACTED-CARD]"
ACCOUNT_TOKEN = "[REDACTED-ACCOUNT]"

# 13 to 19 contiguous digits, not part of a longer digit run.
_CARD_CONTIGUOUS = r"(?<!\d)\d{13,19}(?!\d)"
# 4-4-4-1..7 grouped with a consistent space or dash (Visa, Mastercard, Discover, etc.).
_CARD_GROUPED = r"(?<!\d)\d{4}([ -])\d{4}\1\d{4}\1\d{1,7}(?!\d)"
# Amex style 4-6-5.
_CARD_AMEX = r"(?<!\d)\d{4}([ -])\d{6}\2\d{5}(?!\d)"
CARD_RE = re.compile(f"{_CARD_GROUPED}|{_CARD_AMEX}|{_CARD_CONTIGUOUS}")

# 3-2-4 with a consistent separator (space, dash, or none). Not part of a longer digit run.
SSN_RE = re.compile(r"(?<!\d)\d{3}([ -]?)\d{2}\1\d{4}(?!\d)")

# Digits that follow words like "account" or "routing" (English and Spanish).
ACCOUNT_RE = re.compile(
    r"(?i)\b(account|acct|routing|cuenta|ruta|bancaria)\b([^\d\n]{0,25})(\d[\d -]{4,24}\d)"
)


def redact(text: str) -> str:
    """Return text with SSN-, card-, and account-shaped numbers replaced by tokens."""
    if not text:
        return text
    text = CARD_RE.sub(CARD_TOKEN, text)
    text = SSN_RE.sub(SSN_TOKEN, text)
    text = ACCOUNT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{ACCOUNT_TOKEN}", text)
    return text


def contains_sensitive(text: str) -> bool:
    return bool(text) and redact(text) != text


def redact_obj(obj: Any) -> Any:
    """Recursively redact every string inside a JSON-like structure."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    return obj
