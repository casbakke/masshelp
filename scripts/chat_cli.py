"""Talk to the MassHelp agent in a terminal, as SMS or voice, without Twilio or Vapi.

    uv run scripts/chat_cli.py --phone +16175550101 --channel voice
    uv run scripts/chat_cli.py --phone +16175550102 --channel sms --reset

Commands: /image path.jpg [more paths]  send photos (simulated MMS, always via SMS)
          /sms text                     send one message by text while in voice mode
          /quit
"""

from __future__ import annotations

import argparse
import asyncio
import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from masshelp.agent.runner import UserInput  # noqa: E402
from masshelp.cases import get_or_create_case  # noqa: E402
from masshelp.channels.voice import VOICE_GREETING  # noqa: E402
from masshelp.docs.ingest import IncomingMedia  # noqa: E402
from masshelp.messaging import ConsoleMessenger  # noqa: E402
from masshelp.services import build_services  # noqa: E402
from masshelp.util.phone import normalize_phone  # noqa: E402

from scripts.reset_demo import reset_phone  # noqa: E402


async def turn(services, case_id: str, channel: str, user_input: UserInput) -> None:
    label = "MassHelp (voice)" if channel == "voice" else "MassHelp (sms)"
    print(f"{label}: ", end="", flush=True)
    async for chunk in services.runner.handle(case_id, channel, user_input):
        print(chunk, end="", flush=True)
    print("\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", required=True)
    ap.add_argument("--channel", choices=["sms", "voice"], default="sms")
    ap.add_argument("--reset", action="store_true", help="close this number's case first")
    args = ap.parse_args()

    services = build_services(messenger=ConsoleMessenger())
    phone = normalize_phone(args.phone)
    if args.reset:
        reset_phone(services, phone)

    with services.db.session() as s:
        case = get_or_create_case(s, services.masshealth, phone)
        case_id = case.id
    print(f"[case {case_id}, channel {args.channel}. /image path, /sms text, /quit]\n")

    if args.channel == "voice":
        services.runner.add_assistant_note(case_id, "voice", VOICE_GREETING)
        print(f"MassHelp (voice): {VOICE_GREETING}\n")

    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line == "/quit":
            return
        if line.startswith("/image"):
            paths = line.split()[1:]
            media = []
            for p in paths:
                path = Path(p).expanduser()
                if not path.exists():
                    print(f"[no such file {path}]")
                    continue
                ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                media.append(IncomingMedia(data=path.read_bytes(), content_type=ctype))
            if media:
                await turn(services, case_id, "sms", UserInput(text="", media=media))
            continue
        if line.startswith("/sms "):
            await turn(services, case_id, "sms", UserInput(text=line[5:]))
            continue
        await turn(services, case_id, args.channel, UserInput(text=line))


if __name__ == "__main__":
    asyncio.run(main())
