from __future__ import annotations

import json

from masshelp.agent.runner import UserInput
from masshelp.cases import get_or_create_case


def open_case(services, phone: str, text: str = "") -> str:
    with services.db.session() as s:
        return get_or_create_case(s, services.masshealth, phone, text).id


async def say(services, case_id: str, channel: str, text: str = "", media=None) -> str:
    out = ""
    async for chunk in services.runner.handle(case_id, channel, UserInput(text=text, media=media or [])):
        out += chunk
    return out


def last_tool_result(llm, name: str | None = None) -> dict:
    """Most recent tool_result the runner sent back to the (fake) model."""
    for call in reversed(llm.calls):
        for msg in reversed(call["messages"]):
            if msg["role"] != "user":
                continue
            for block in reversed(msg["content"]):
                if block["type"] == "tool_result":
                    return json.loads(block["content"])
    raise AssertionError("no tool result found")


def capture(store: dict, key: str):
    """Script item that records the latest tool result into `store[key]` and returns text."""
    def responder(request):
        for msg in reversed(request["messages"]):
            if msg["role"] == "user":
                for b in msg["content"]:
                    if b["type"] == "tool_result":
                        store[key] = json.loads(b["content"])
                break
        return None
    return responder
