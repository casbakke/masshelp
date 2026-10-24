# MassHelp

A free automated assistant that helps MassHealth members prove they meet the new Medicaid work rule (starting January 1, 2027), so they don't lose coverage over paperwork. Members **call or text**. MassHelp verifies who they are, finds the shortest way to show they qualify, collects proof (photos are fine), fills the MassHealth **Attestation Form to Verify Income (AFVI)**, gets explicit consent, and submits to a **mock** MassHealth intake.

Hackachusetts, Civic Services track. Built with Kiro: see `.kiro/` and [KIRO_NOTES.md](KIRO_NOTES.md). Why: [VISION.md](VISION.md). Full spec: [SPEC.md](SPEC.md).

All MassHealth systems are mocks with dummy data. Nothing is sent to MassHealth. Every PDF is watermarked "SAMPLE - NOT FOR SUBMISSION".

## Quick start

```sh
uv sync
cp .env.example .env          # add ANTHROPIC_API_KEY
uv run pytest                 # 42 tests, no API key needed
uv run scripts/chat_cli.py --phone +16175550101 --channel voice   # Maria (demo 9.1)
uv run scripts/chat_cli.py --phone +16175550102 --channel sms     # Carlos (demo 9.2, Spanish)
```

In the CLI: `/image seed/sample_docs/earnings_maria.png` simulates an MMS photo, `/sms text` sends one text during a voice session, `--reset` starts the number fresh.

## Run with real phones

1. `uv run uvicorn masshelp.main:app --port 8000` and `ngrok http 8000`. Set `PUBLIC_BASE_URL` to the ngrok URL.
2. Twilio: set the number's messaging webhook to `POST {PUBLIC_BASE_URL}/twilio/sms`. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`.
3. Vapi: create an assistant from `vapi/assistant.example.json` with Custom LLM URL `{PUBLIC_BASE_URL}/vapi`. Set `VAPI_SECRET` to the API key Vapi sends.
4. Put the team's phones in `DEMO_PHONE_MARIA` / `DEMO_PHONE_CARLOS`, then `uv run scripts/reset_demo.py`.

Security: Twilio webhooks are signature-checked (`TWILIO_VALIDATE=true`), the Vapi endpoint requires `VAPI_SECRET` when set (set it for any public URL), and PDF links use random tokens that expire after 7 days. There is no other auth; this is a demo with dummy data.

## Demo members (`seed/members.yaml`, `DEMO_TODAY=2026-12-01`)

| Member | DOB | Scenario |
| --- | --- | --- |
| Maria Santos, MH-DEMO-000123 | 1992-06-04 | Voice, delivery app driver, no pay stubs, sends a screenshot |
| Carlos Rivera, MH-DEMO-000456 | 1985-03-17 | SMS in Spanish, landscaping job, paper paystubs |
| Ana Lopez, MH-DEMO-000789 | 1990-09-12 | Parent of a 10-year-old (exemption) |
| Jamal Brown, MH-DEMO-000321 | 2003-01-25 | Half-time student (school path) |
| Linh Nguyen, MH-DEMO-000654 | 1978-11-02 | $300 income + 50 volunteer hours (combination) |
| David Miller, MH-DEMO-000987 | 1988-04-30 | Lost job (honest "likely does not meet") |

## How it works

- `masshelp/rules/engine.py`: pure, deterministic rules. The only source of outcomes. Policy numbers live in `masshelp/rules/masshealth_rules.yaml`.
- `masshelp/agent/runner.py`: streams Claude Haiku with 12 server-side tools; the same transcript serves SMS and voice, so a case started on a call continues by text.
- `masshelp/forms/afvi.py`: fills and flattens the AFVI form. AFVI covers income-based paths only; for exemptions or school, the agent gives the MassHealth number.
- `masshelp/channels/`: Twilio webhook and Vapi custom-LLM SSE adapter.

## Scripts

`chat_cli.py` (terminal agent), `reset_demo.py`, `seed_db.py`, `make_sample_docs.py`, `gen_policy_docs.py` (rules YAML to steering doc), `scan_secrets.py`, `latency_report.py`.
