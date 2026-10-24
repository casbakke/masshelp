---
inclusion: always
---

# Structure

## Root

- `.kiro/`: Kiro specs, steering, and hooks. Committed; never gitignore it.
- `VISION.md`: why MassHelp exists; mission and principles.
- `SPEC.md`: implementation spec; source of R1 to R37.
- `README.md`: setup, run, demo instructions, and Kiro write-up link.
- `KIRO_NOTES.md`: running log of how Kiro was used, for the submission write-up.
- `pyproject.toml`: project metadata and dependencies, managed with uv.
- `.env.example`: every env var with placeholder values.

## App (`masshelp/`)

- `masshelp/main.py`: FastAPI app and routes (`/health`, `/twilio/sms`, `/vapi/chat/completions`, `/files/{token}`).
- `masshelp/config.py`: settings loaded from env with pydantic-settings.
- `masshelp/i18n.py`: fixed English and Spanish SMS templates.
- `masshelp/messaging.py`: Messenger interface with Twilio, console, and fake implementations.
- `masshelp/channels/sms.py`: Twilio SMS/MMS webhook adapter.
- `masshelp/channels/voice.py`: Vapi custom LLM adapter that streams OpenAI-style SSE.
- `masshelp/agent/runner.py`: `AgentRunner.handle`; channel-agnostic Claude tool loop and transcript persistence.
- `masshelp/agent/tools.py`: tool schemas and dispatch.
- `masshelp/agent/llm.py`: LLM client protocol, Anthropic implementation, and scripted fake for tests.
- `masshelp/agent/context.py`: builds the per-turn context block that goes after the cache breakpoint.
- `masshelp/agent/prompts/system.md`: static, cached system prompt, including the generated policy section.
- `masshelp/rules/engine.py`: pure, deterministic rules engine; the only source of outcomes.
- `masshelp/rules/models.py`: types for member facts, months, rules config, and evaluations.
- `masshelp/rules/masshealth_rules.yaml`: every threshold, exemption, and proof type.
- `masshelp/docs/extract.py`: vision extraction of document fields to structured JSON.
- `masshelp/docs/reconcile.py`: compares document amounts with stated amounts and flags differences.
- `masshelp/forms/afvi.py`: fills and flattens the AFVI PDF (`assets/AFVI_2025-10.pdf`), SAMPLE watermark on every page. AFVI is the only supported form.
- `masshelp/forms/afvi_mapping.yaml`: AFVI AcroForm field names.
- `masshelp/forms/build.py`: case state to AFVI content and read-back fields; honors `DEMO_FIXED_PDF`.
- `masshelp/answers.py`: answer field enum, parsing, and facts builder for the engine.
- `masshelp/cases.py`: case lookup (one open case per phone) and identity state.
- `masshelp/services.py`: wires settings, db, rules, LLM, messenger, and the mock MassHealth client.
- `masshelp/docs/ingest.py`: stores media, runs extraction, records document-sourced answers.
- `masshelp/rules/policy_text.py`: renders the rules YAML as markdown for the prompt and `policy.md`.
- `masshelp/masshealth_mock/service.py`: mock `MassHealthClient` for member lookup, open requests, and submission.
- `masshelp/store/models.py`: SQLModel tables (Member, Case, Message, Answer, Document, Consent, Submission, Event).
- `masshelp/store/db.py`: database engine and session setup.
- `masshelp/store/files.py`: random, expiring file tokens for `/files/{token}` links.
- `masshelp/util/redact.py`: removes SSN-like and card-like patterns from text.
- `masshelp/util/phone.py`: phone number normalization to E.164.
- `masshelp/util/dates.py`: `today()` that honors `DEMO_TODAY`.
- `masshelp/util/lang.py`: light language guess from member text.

## Seed data (`seed/`)

- `seed/members.yaml`: demo members; phone numbers come from `DEMO_PHONE_*` env vars.
- `seed/sample_docs/`: synthetic paystubs and earnings screenshot, clearly fake, no real logos.

## Scripts (`scripts/`)

- `scripts/chat_cli.py`: talk to the agent in a terminal as SMS or voice; `/image path.jpg` simulates MMS.
- `scripts/seed_db.py`: loads seed members into the database.
- `scripts/reset_demo.py`: resets demo cases to a clean start.
- `scripts/gen_policy_docs.py`: regenerates the policy section of the system prompt and `.kiro/steering/policy.md` from the rules YAML.
- `scripts/make_sample_docs.py`: generates the synthetic sample documents.
- `scripts/scan_secrets.py`: scans the diff for secrets and real-looking SSNs.
- `scripts/latency_report.py`: prints p50 and p95 voice time to first token from `Event` logs.

## Voice config (`vapi/`)

- `vapi/assistant.example.json`: example Vapi assistant config (first message, voice, end-call phrase, custom LLM URL).

## Tests (`tests/`)

- `tests/test_rules_engine.py`: unit tests for every path, exemption, and edge value.
- `tests/test_rules_properties.py`: Hypothesis property tests for the engine.
- `tests/test_redact.py`: redaction tests, including Hypothesis.
- `tests/test_sms_webhook.py`: Twilio webhook tests.
- `tests/test_vapi_stream.py`: Vapi SSE format tests.
- `tests/test_forms.py`: PDF fill and watermark tests.
- `tests/conversations/`: scripted end-to-end runs with the fake LLM.

## Runtime (`data/`)

- `data/`: SQLite database, received media, and generated PDFs. Gitignored.

## Conventions

- Channel adapters stay thin. They parse the channel event, call `AgentRunner.handle`, and send the text back.
- All member-facing fixed strings live in `masshelp/i18n.py`.
- All policy numbers live in `masshelp/rules/masshealth_rules.yaml`.
- Tools return JSON-serializable dicts.
