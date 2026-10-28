---
inclusion: always
---

# Tech

## Stack

- Python 3.12+
- FastAPI and Uvicorn for the web app (Twilio and Vapi webhooks, file links)
- `anthropic` official Python SDK for every LLM call
- SQLModel on SQLite
- `twilio` Python SDK for SMS and MMS
- `pypdf` to fill AcroForm PDFs; `reportlab` to generate the mock form and the SAMPLE watermark
- `pydantic-settings` for config from env; `pyyaml` for the rules file
- `pytest`, `hypothesis` (property-based tests), `respx` (HTTP mocks)
- `uv` for dependencies and for running everything
- ngrok or Cloudflare Tunnel for a public URL during local runs

All config comes from env through `pydantic-settings`. See `.env.example`. Never commit real secrets.

## LLM rules

These are hard rules from SPEC 5.2. Do not change them without updating the spec.

- Conversation model is `claude-haiku-5-5`, read from `MASSHELP_MODEL`. `MASSHELP_HEAVY_MODEL` (for example `claude-sonnet-5-5`) is optional and only for document extraction, if tests show Haiku is unreliable on photos.
- Stream every conversation response (`client.messages.stream(...)`).
- Send `thinking={"type": "disabled"}` with `output_config={"effort": "low"}`.
- Never send `temperature`, `top_p`, or `top_k`.
- Never prefill an assistant message.
- `tool_choice` stays `auto`.
- Tool schemas are strict: `strict: true` and `additionalProperties: false`.
- Put `cache_control` at the end of the static system prompt plus tool list. Dynamic per-turn context (date, channel, member summary, case state, language) goes after the cache breakpoint. Expect `usage.cache_read_input_tokens > 0` on the second turn.
- `max_tokens` is 1024 for voice turns and 2048 for SMS turns.
- Handle `stop_reason == "refusal"` in code with the R36 fallback message. Haiku has no server-side fallback.
- Parse tool inputs as JSON (`json.loads` or the SDK's parsed object), never by string matching.
- Document extraction is a separate, non-streaming call: the image as a base64 `image` block, with structured output (`output_config.format` and a JSON schema).
- The tool loop runs at most 6 tool rounds per user turn, then stops with a safe message.

## Commands

- `uv sync`: install dependencies
- `uv run pytest`: run the test suite (no API key needed)
- `uv run pytest -m live`: run the demo scenarios against the real Claude API (needs `ANTHROPIC_API_KEY`)
- `uv run uvicorn masshelp.main:app --reload --port 8000`: run the app locally
- `uv run scripts/chat_cli.py --phone +16175550101 --channel voice`: talk to the agent in a terminal; use `--channel sms` for SMS style and `/image path.jpg` to simulate MMS
- `uv run scripts/seed_db.py`: load seed members into the database
- `uv run scripts/reset_demo.py`: reset demo cases to a clean start

## Testing rules

- CI must not need an API key. Tests use the fake LLM client, never the real API. Only the `live` marker calls Claude.
- The rules engine stays pure: no I/O, no LLM, no network, no database. It takes facts, a month, and the rules config, and returns an evaluation.
