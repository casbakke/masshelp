"""Wires settings, database, rules, LLM, messenger, and the mock MassHealth client."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlmodel import select

from masshelp.agent.llm import AnthropicLLM, LLMClient, LLMError, LLMResult, TextDelta
from masshelp.config import Settings, get_settings
from masshelp.masshealth_mock.service import MassHealthClient, MockMassHealthClient, seed_members
from masshelp.messaging import ConsoleMessenger, Messenger, TwilioMessenger
from masshelp.rules.models import RulesConfig, load_rules
from masshelp.store.db import Database
from masshelp.store.models import Member

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from masshelp.agent.runner import AgentRunner

log = logging.getLogger(__name__)


class LockRegistry:
    """asyncio locks keyed by string (case id or phone number)."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, key: str) -> asyncio.Lock:
        return self._locks[key]


class MissingKeyLLM:
    """Used when ANTHROPIC_API_KEY isn't set: every call fails, so the runner sends
    the safe fallback message instead of crashing."""

    async def stream(self, **_: Any) -> AsyncIterator[TextDelta | LLMResult]:
        raise LLMError("ANTHROPIC_API_KEY is not set")
        yield  # pragma: no cover - makes this an async generator

    async def extract(self, **_: Any) -> dict | None:
        raise LLMError("ANTHROPIC_API_KEY is not set")


@dataclass
class Services:
    settings: Settings
    db: Database
    rules: RulesConfig
    llm: LLMClient
    messenger: Messenger
    masshealth: MassHealthClient
    locks: LockRegistry
    runner: AgentRunner | None = None


def default_llm(settings: Settings) -> LLMClient:
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY not set; agent replies will be the fallback message")
        return MissingKeyLLM()
    return AnthropicLLM(settings.anthropic_api_key, settings.masshelp_model, settings.masshelp_heavy_model)


def default_messenger(settings: Settings) -> Messenger:
    if settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_phone_number:
        return TwilioMessenger(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number)
    log.warning("Twilio not configured; outbound SMS will be printed to the console")
    return ConsoleMessenger()


def build_services(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    messenger: Messenger | None = None,
    seed: bool = True,
) -> Services:
    from masshelp.agent.runner import AgentRunner

    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.resolved_database_url)
    db.init()
    services = Services(
        settings=settings,
        db=db,
        rules=load_rules(settings.rules_path),
        llm=llm or default_llm(settings),
        messenger=messenger or default_messenger(settings),
        masshealth=MockMassHealthClient(db),
        locks=LockRegistry(),
    )
    if seed:
        with db.session() as s:
            empty = s.exec(select(Member)).first() is None
        if empty:
            seed_members(db, settings)
    services.runner = AgentRunner(services)
    return services
