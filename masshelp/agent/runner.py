"""Channel-agnostic agent runner (SPEC 5.4).

handle() appends the member's input to the transcript, runs Claude with tools until
end_turn (max 6 tool rounds), streams assistant text out, and persists every content
block so history replays exactly across SMS and voice (G3).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlmodel import Session, col, select

from masshelp.agent.context import build_context
from masshelp.agent.llm import LLMError, LLMResult, TextDelta
from masshelp.agent.tools import SLOW_TOOLS, ToolContext, run_tool, tool_definitions
from masshelp.cases import identity_locked, touch
from masshelp.docs.ingest import IncomingMedia, ingest_media
from masshelp.i18n import t
from masshelp.rules.policy_text import policy_markdown
from masshelp.store.db import log_event
from masshelp.store.models import Case, Message
from masshelp.util.dates import utcnow
from masshelp.util.redact import contains_sensitive, redact, redact_obj

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).with_name("prompts") / "system.md"
HISTORY_LIMIT = 80
SENSITIVE_NOTE = (
    "[System note: the member shared a number that looks like a Social Security, card, or bank number. "
    "It was removed. Tell them kindly that MassHelp never needs it.]"
)


@dataclass
class UserInput:
    text: str = ""
    media: list[IncomingMedia] = field(default_factory=list)


DEMO_SCRIPT_PATH = Path(__file__).with_name("prompts") / "demo_script.md"


def load_system_prompt(rules, demo_script: bool = False) -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{{POLICY}}", policy_markdown(rules))
    if demo_script:
        prompt += "\n\n" + DEMO_SCRIPT_PATH.read_text(encoding="utf-8")
    return prompt


class AgentRunner:
    def __init__(self, services):
        self.services = services
        self.system_prompt = load_system_prompt(services.rules, services.settings.demo_script)
        self.tools = tool_definitions(services.rules)

    # ------------------------------------------------------------ public

    async def handle(self, case_id: str, channel: str, user_input: UserInput) -> AsyncIterator[str]:
        lock = self.services.locks.get(case_id)
        async with lock:
            async for chunk in self._handle(case_id, channel, user_input):
                yield chunk

    def add_assistant_note(self, case_id: str, channel: str, text: str) -> None:
        """Record something said outside the LLM (e.g. the Vapi greeting) so history matches."""
        with self.services.db.session() as s:
            self._save(s, case_id, channel, "assistant", [{"type": "text", "text": text}])

    # ------------------------------------------------------------ internals

    async def _handle(self, case_id: str, channel: str, user_input: UserInput) -> AsyncIterator[str]:
        services = self.services
        settings = services.settings
        started = time.perf_counter()

        with services.db.session() as s:
            case = s.get(Case, case_id)
            if channel == "sms" and case.opted_out:
                return
            lang = case.language
            if identity_locked(case, settings):
                text = t("identity_locked", lang, phone=services.rules.contacts["masshealth_customer_service"])
                self._save(s, case_id, channel, "user", [{"type": "text", "text": redact(user_input.text) or "(no text)"}])
                self._save(s, case_id, channel, "assistant", [{"type": "text", "text": text}])
                yield text
                return

        # Documents first (vision extraction), outside the DB session.
        doc_note = await ingest_media(services, case_id, user_input.media) if user_input.media else ""

        with services.db.session() as s:
            case = s.get(Case, case_id)
            disclosure = self._needs_sms_disclosure(s, case) if channel == "sms" else False
            clean = redact(user_input.text or "")
            parts = [p for p in (clean, doc_note) if p]
            if contains_sensitive(user_input.text or ""):
                parts.append(SENSITIVE_NOTE)
                log_event(s, case_id, "sensitive_redacted", {"channel": channel})
            user_blocks = [{"type": "text", "text": "\n\n".join(parts) or "(empty message)"}]
            user_msg = self._save(s, case_id, channel, "user", user_blocks)
            ctx = ToolContext(services, case_id, channel, user_msg.id, clean)

        if disclosure:
            yield t("disclosure_sms", lang) + "\n\n"

        max_tokens = settings.max_tokens_voice if channel == "voice" else settings.max_tokens_sms
        first_token_at: float | None = None
        emitted_any = False
        rounds = 0
        try:
            while True:
                with services.db.session() as s:
                    case = s.get(Case, case_id)
                    context = build_context(services, s, case, channel, sms_disclosure_added=disclosure)
                    messages = self._history(s, case_id)
                system = [
                    {"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "# Current context\n" + context},
                ]
                result: LLMResult | None = None
                round_text = False
                async for event in services.llm.stream(system=system, tools=self.tools, messages=messages,
                                                       max_tokens=max_tokens):
                    if isinstance(event, TextDelta):
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                        if emitted_any and not round_text:
                            yield " "
                        round_text = True
                        yield event.text
                    else:
                        result = event
                if round_text:
                    emitted_any = True
                if result is None:
                    raise LLMError("stream ended without a final message")

                if result.stop_reason == "refusal":
                    with services.db.session() as s:
                        log_event(s, case_id, "llm_refusal", {"round": rounds})
                    fallback = t("fallback", lang)
                    with services.db.session() as s:
                        self._save(s, case_id, channel, "assistant", [{"type": "text", "text": fallback}])
                    yield fallback
                    return

                with services.db.session() as s:
                    self._save(s, case_id, channel, "assistant", result.content)
                    if rounds == 0:
                        log_event(s, case_id, "llm_usage", {"usage": result.usage})

                tool_uses = [b for b in result.content if b["type"] == "tool_use"]
                if result.stop_reason != "tool_use" or not tool_uses:
                    if not emitted_any:
                        fallback = t("fallback", lang)
                        with services.db.session() as s:
                            self._save(s, case_id, channel, "assistant", [{"type": "text", "text": fallback}])
                        yield fallback
                    return

                rounds += 1
                results = []
                for tu in tool_uses:
                    output = await run_tool(ctx, tu["name"], tu["input"])
                    results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                    "content": json.dumps(output, default=str, ensure_ascii=False)})
                with services.db.session() as s:
                    self._save(s, case_id, channel, "user", results)
                if rounds >= settings.max_tool_rounds:
                    text = t("too_many_steps", lang)
                    with services.db.session() as s:
                        log_event(s, case_id, "tool_round_limit", {"rounds": rounds})
                        self._save(s, case_id, channel, "assistant", [{"type": "text", "text": text}])
                    yield (" " if emitted_any else "") + text
                    return
        except LLMError as exc:
            log.warning("LLM error: %s", exc)
            fallback = t("fallback", lang)
            with services.db.session() as s:
                log_event(s, case_id, "llm_error", {"error": str(exc)[:500]})
                self._save(s, case_id, channel, "assistant", [{"type": "text", "text": fallback}])
            yield (" " if emitted_any else "") + fallback
        finally:
            with services.db.session() as s:
                case = s.get(Case, case_id)
                if case is not None:
                    touch(s, case)
                log_event(s, case_id, "turn_latency", {
                    "channel": channel,
                    "ttft_ms": round((first_token_at - started) * 1000) if first_token_at else None,
                    "total_ms": round((time.perf_counter() - started) * 1000),
                    "tool_rounds": rounds,
                })

    def _needs_sms_disclosure(self, s: Session, case: Case) -> bool:
        """R32: the first SMS reply of a conversation says it's automated, not MassHealth."""
        last = s.exec(select(Message).where(Message.case_id == case.id, Message.role == "assistant",
                                            Message.channel == "sms")
                      .order_by(col(Message.id).desc())).first()
        if last is None:
            return True
        gap = timedelta(hours=self.services.settings.sms_conversation_gap_hours)
        return utcnow() - last.created_at > gap

    def _save(self, s: Session, case_id: str, channel: str, role: str, blocks: list[dict]) -> Message:
        blocks = redact_obj(blocks)
        text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        msg = Message(case_id=case_id, channel=channel, role=role,
                      content_json=json.dumps(blocks, ensure_ascii=False), redacted_text=text)
        s.add(msg)
        s.commit()
        return msg

    def _history(self, s: Session, case_id: str) -> list[dict]:
        rows = list(s.exec(select(Message).where(Message.case_id == case_id).order_by(col(Message.id).desc())
                           .limit(HISTORY_LIMIT)))
        rows.reverse()
        messages: list[dict] = []
        for row in rows:
            blocks = row.content
            if row.role == "user":
                blocks = [
                    {**b, "text": f"[{'phone call' if row.channel == 'voice' else 'text message'}] {b['text']}"}
                    if b["type"] == "text" else b
                    for b in blocks
                ]
            if messages and messages[-1]["role"] == row.role:
                messages[-1]["content"].extend(blocks)
            else:
                messages.append({"role": row.role, "content": list(blocks)})
        # Must start with a user message that isn't an orphan tool_result.
        while messages and (messages[0]["role"] != "user" or
                            any(b["type"] == "tool_result" for b in messages[0]["content"])):
            messages.pop(0)
        # Tool results must come before any text in a merged user message.
        for m in messages:
            if m["role"] == "user":
                m["content"].sort(key=lambda b: 0 if b["type"] == "tool_result" else 1)
        return messages
