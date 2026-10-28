"""Outbound SMS. Only used to reply inside an active conversation or to send a
confirmation the member was told about (R3). Never sends to opted-out cases (R4).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from sqlmodel import Session

from masshelp.store.db import log_event
from masshelp.store.models import Case
from masshelp.util.dates import utcnow
from masshelp.util.phone import last_four
from masshelp.util.redact import redact

log = logging.getLogger(__name__)


class Messenger(Protocol):
    async def send_sms(self, to: str, body: str, media_urls: list[str] | None = None) -> str | None: ...


class TwilioMessenger:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        from twilio.rest import Client

        self.client = Client(account_sid, auth_token)
        self.from_number = from_number

    async def send_sms(self, to: str, body: str, media_urls: list[str] | None = None) -> str | None:
        def _send() -> str:
            kwargs = {"to": to, "from_": self.from_number, "body": body}
            if media_urls:
                kwargs["media_url"] = media_urls
            return self.client.messages.create(**kwargs).sid

        return await asyncio.to_thread(_send)


class ConsoleMessenger:
    """Prints outbound texts. Used by scripts/chat_cli.py and when Twilio isn't configured.
    Nothing reaches the member, so sends report as not delivered."""

    delivers = False

    async def send_sms(self, to: str, body: str, media_urls: list[str] | None = None) -> str | None:
        media = f"\n   [media: {', '.join(media_urls)}]" if media_urls else ""
        print(f"\n   >>> SMS to ...{last_four(to)}: {body}{media}\n", flush=True)
        return None


@dataclass
class SentSms:
    to: str
    body: str
    media_urls: list[str] | None


@dataclass
class FakeMessenger:
    """Records outbound texts for tests."""

    sent: list[SentSms] = field(default_factory=list)

    async def send_sms(self, to: str, body: str, media_urls: list[str] | None = None) -> str | None:
        self.sent.append(SentSms(to=to, body=body, media_urls=media_urls))
        return f"SM{len(self.sent):04d}"


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"'(])")


def split_sms(text: str, limit: int = 600) -> list[str]:
    """Split long replies into parts of at most `limit` characters.

    Lines (so numbered lists survive) are kept whole when they fit; long lines are
    split at sentence boundaries, and only a single huge sentence is hard-wrapped.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    # Units are (separator_before, piece).
    units: list[tuple[str, str]] = []
    for line_no, line in enumerate(text.split("\n")):
        line_sep = "\n" if line_no > 0 else ""
        pieces = [line] if len(line) <= limit else _split_long_line(line, limit)
        for i, piece in enumerate(pieces):
            units.append((line_sep if i == 0 else " ", piece))

    parts: list[str] = []
    current = ""
    for sep, piece in units:
        candidate = f"{current}{sep}{piece}" if current else piece
        if len(candidate) <= limit:
            current = candidate
        else:
            if current.strip():
                parts.append(current.strip())
            current = piece
    if current.strip():
        parts.append(current.strip())
    return parts


def _split_long_line(line: str, limit: int) -> list[str]:
    out: list[str] = []
    for sentence in _SENTENCE_END.split(line):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


async def send_case_sms(
    messenger: Messenger,
    session: Session,
    case: Case,
    body: str,
    *,
    media_urls: list[str] | None = None,
    limit: int = 600,
    kind: str = "reply",
) -> bool:
    """Send an SMS to the case's phone, honoring opt-out. Returns True if sent."""
    if case.opted_out:
        log_event(session, case.id, "sms_suppressed_opted_out", {"kind": kind})
        return False
    parts = split_sms(body, limit)
    if not parts:
        return False
    try:
        for i, part in enumerate(parts):
            # Attach media to the last part only.
            await messenger.send_sms(case.phone_e164, part, media_urls if i == len(parts) - 1 else None)
    except Exception as exc:  # noqa: BLE001 - log and report failure, never crash the turn
        log.exception("SMS send failed")
        log_event(session, case.id, "sms_error", {"kind": kind, "error": str(exc)[:300]})
        return False
    delivered = getattr(messenger, "delivers", True)
    case.last_sms_out_at = utcnow()
    session.add(case)
    log_event(session, case.id, "sms_sent" if delivered else "sms_console_only",
              {"kind": kind, "parts": len(parts), "text": redact(body)[:1000]})
    return delivered
