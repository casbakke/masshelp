"""LLM clients.

AnthropicLLM follows SPEC 5.2: stream every conversation turn, thinking disabled with
effort low, no temperature/top_p/top_k, no assistant prefill, tool_choice auto.
ScriptedLLM replays canned responses so tests and CI never need an API key.
"""

from __future__ import annotations

import base64
import itertools
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)


@dataclass
class TextDelta:
    text: str


@dataclass
class LLMResult:
    content: list[dict[str, Any]]
    stop_reason: str
    usage: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def stream(
        self, *, system: list[dict], tools: list[dict], messages: list[dict], max_tokens: int
    ) -> AsyncIterator[TextDelta | LLMResult]: ...

    async def extract(self, *, content: list[dict], schema: dict, max_tokens: int = 1024) -> dict | None: ...


def clean_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    """Keep only what we replay: text and tool_use blocks, in the API's input shape."""
    out: list[dict[str, Any]] = []
    for b in blocks:
        d = b if isinstance(b, dict) else b.model_dump()
        if d.get("type") == "text":
            if d.get("text"):
                out.append({"type": "text", "text": d["text"]})
        elif d.get("type") == "tool_use":
            out.append({"type": "tool_use", "id": d["id"], "name": d["name"], "input": d.get("input") or {}})
    return out


class AnthropicLLM:
    def __init__(self, api_key: str | None, model: str, extract_model: str | None = None):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.extract_model = extract_model or model

    async def stream(
        self, *, system: list[dict], tools: list[dict], messages: list[dict], max_tokens: int
    ) -> AsyncIterator[TextDelta | LLMResult]:
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                thinking={"type": "disabled"},
                extra_body={"output_config": {"effort": "low"}},
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield TextDelta(text)
                final = await stream.get_final_message()
        except self._anthropic.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        usage = final.usage.model_dump() if final.usage else {}
        yield LLMResult(content=clean_blocks(final.content), stop_reason=final.stop_reason or "end_turn", usage=usage)

    async def extract(self, *, content: list[dict], schema: dict, max_tokens: int = 1024) -> dict | None:
        """Non-streaming structured extraction (SPEC 5.2). Returns parsed JSON or None."""
        output_config = {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
        kwargs: dict[str, Any] = {
            "model": self.extract_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        try:
            try:
                resp = await self.client.messages.create(
                    **kwargs, thinking={"type": "disabled"}, extra_body={"output_config": output_config}
                )
            except self._anthropic.BadRequestError as exc:
                # Some heavier models don't accept disabled thinking. Retry without it.
                if "thinking" not in str(exc):
                    raise
                resp = await self.client.messages.create(**kwargs, extra_body={"output_config": output_config})
        except self._anthropic.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        if resp.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("extraction returned non-JSON text")
            return None


# ---------------------------------------------------------------- fake for tests

_ids = itertools.count(1)


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def tool_block(name: str, **input_: Any) -> dict:
    return {"type": "tool_use", "id": f"toolu_fake_{next(_ids):04d}", "name": name, "input": input_}


Responder = Callable[[dict[str, Any]], list[dict] | LLMResult]


@dataclass
class ScriptedLLM:
    """Replays scripted responses in order.

    Each script item is either a list of content blocks, an LLMResult (to force
    stop_reason, e.g. "refusal"), an Exception (raised), or a callable that gets the
    request and returns one of those.
    """

    script: list[Any] = field(default_factory=list)
    extractions: list[dict | None] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    extract_calls: list[dict[str, Any]] = field(default_factory=list)
    chunk_size: int = 12

    def add(self, *items: Any) -> ScriptedLLM:
        self.script.extend(items)
        return self

    async def stream(
        self, *, system: list[dict], tools: list[dict], messages: list[dict], max_tokens: int
    ) -> AsyncIterator[TextDelta | LLMResult]:
        request = {"system": system, "tools": tools, "messages": json.loads(json.dumps(messages)), "max_tokens": max_tokens}
        self.calls.append(request)
        if not self.script:
            raise LLMError("ScriptedLLM ran out of scripted responses")
        item = self.script.pop(0)
        if callable(item) and not isinstance(item, (list, LLMResult)):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        result = item if isinstance(item, LLMResult) else LLMResult(
            content=item,
            stop_reason="tool_use" if any(b["type"] == "tool_use" for b in item) else "end_turn",
        )
        if result.stop_reason != "refusal":
            for block in result.content:
                if block["type"] == "text":
                    t = block["text"]
                    for i in range(0, len(t), self.chunk_size):
                        yield TextDelta(t[i : i + self.chunk_size])
        yield LLMResult(content=clean_blocks(result.content), stop_reason=result.stop_reason, usage={"fake": True})

    async def extract(self, *, content: list[dict], schema: dict, max_tokens: int = 1024) -> dict | None:
        self.extract_calls.append({"content": content, "schema": schema})
        if not self.extractions:
            return None
        return self.extractions.pop(0)


def image_block(data: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()},
    }


def pdf_block(data: bytes) -> dict:
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode()},
    }
