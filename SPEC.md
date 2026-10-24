# MassHelp Implementation Spec

> Handoff spec for the implementing agent. Read `VISION.md` first for the why. This file is the what and the how.
>
> Status: v1 draft, 2026-10-24. Items marked **[DEFAULT]** were chosen without confirmation from the team and may change. Items marked **[VERIFY]** depend on third-party behavior that must be checked against current docs before relying on it.

---

## 1. Summary

MassHelp is a headless AI assistant that helps MassHealth members prove they meet the new Medicaid work and community engagement rule, so they don't lose coverage over paperwork.

A member **calls or texts** the MassHelp number. The agent:

1. Identifies the member and confirms who they are.
2. Explains, in plain language and in the member's language, what is needed and why.
3. Interviews them to find the shortest path to compliance (exemption first, then income, then hours).
4. Collects proof, including photos of paystubs or gig-app earnings screens sent by text.
5. Autofills the verification form as a PDF.
6. Reads the answers back, gets explicit consent, and submits on the member's behalf to a (mock) MassHealth intake.
7. Texts a confirmation with the filled PDF.

There is no web or mobile frontend. The only surfaces are **SMS (Twilio)** and **voice (Vapi)**. All MassHealth systems are **mocks** with dummy data.

### Hackathon context

- Track: **Civic Services** (Hackachusetts).
- Must be built with **Kiro**. The `/.kiro` directory must be committed at the repo root and never gitignored. Judges score how Kiro was used (specs, hooks, steering, MCP, property-based testing, powers). See section 11.
- The repo must be public and contain everything needed to run.
- The demo video must be under 3 minutes and must not contain third-party trademarks without permission. Refer to "a food delivery app" in the video, not by brand name (it is fine in code and seed data).

---

## 2. Goals and non-goals

### Goals (MVP)

- G1. A member can complete a work-requirement verification **entirely by phone call**.
- G2. A member can complete it **entirely by SMS**, including sending photos of documents.
- G3. A case started on one channel continues on the other (for example, call first, then text a photo).
- G4. Eligibility logic is **deterministic code**, not LLM judgment. The LLM gathers facts and explains; the rules engine decides "likely meets".
- G5. English and Spanish work end to end. Other languages work best-effort through the LLM.
- G6. The two demo scenarios in section 9 run reliably, repeatably, with seeded data.

### Non-goals (MVP)

- **No outbound contact.** The agent never calls or texts first. The member always starts. Reminders and outreach are future work (section 12).
- No real MassHealth integration, real member data, or real submission.
- No web UI, navigator console, or admin dashboard.
- No eligibility decisions. The agent always says "likely meets" and "MassHealth makes the final decision."
- No legal advice, no appeals handling (it may give the MassHealth phone number and suggest legal aid).
- No SSN, bank account, or card number collection, ever.

---

## 3. Policy background the agent must get right

Source: H.R. 1 (One Big Beautiful Bill Act, July 2025), Medicaid community engagement requirement, effective **January 1, 2027** for the ACA expansion adult group aged 19 to 64. Massachusetts has not published final implementation details. **All thresholds, exemptions, and accepted proof types live in a config file (`rules/masshealth_rules.yaml`), never hard-coded in prompts**, so they can be updated as guidance changes.

### 3.1 Who it applies to

Expansion-group adults (MassHealth CarePlus), aged 19 to 64, who are not exempt.

### 3.2 Ways to meet the rule (any one, for a given month)

| Path | Requirement |
| --- | --- |
| Hours | At least **80 hours in the month** of any combination of work, community service/volunteering, or a work program/job training |
| School | Enrolled **at least half-time** in an educational program |
| Income | Monthly income of at least **80 × federal minimum wage = 80 × $7.25 = $580** |
| Seasonal income | For seasonal workers: average monthly income over the prior 6 months of at least $580 |

Note on combinations: hours from work, volunteering, and training add up. Income can also be converted to hours (`income / 7.25`) and combined with volunteer or training hours. **[DEFAULT]** Treat this as allowed and flag it in the case notes as "combination path, confirm with MassHealth guidance."

Note on self-employment and gig work: use **net** earnings (gross minus business expenses such as gas and mileage). Collect both gross and expenses when the member knows them. **[DEFAULT]** If the member doesn't know expenses, use gross and add a note.

### 3.3 Exemptions (check these FIRST; an exempt person should not be asked about hours)

- Parent or caretaker of a dependent child **13 or younger**, or of a person with a disability
- Pregnant, or postpartum
- Medically frail: blind or disabled, substance use disorder, disabling mental disorder, physical/intellectual/developmental disability that significantly impairs daily activities, or a serious or complex medical condition
- In a substance use disorder treatment program
- Already meeting SNAP or TAFDC (TANF) work requirements
- Incarcerated, or released within the last 90 days
- American Indian / Alaska Native
- Veteran with a total disability rating
- Former foster youth under 26
- Short-term hardship (state option; MA has not decided): inpatient hospital stay, living in a disaster or high-unemployment area

Exempt members may still have to prove the exemption. The agent records which exemption is claimed and what proof the member has.

### 3.4 Other changes the agent should explain when relevant

- Renewals move from every 12 months to **every 6 months** for this group.
- Retroactive coverage shrinks from **3 months to 1 month**, so a coverage gap now means real medical debt.
- Coverage continues while a response is pending within the deadline. **[VERIFY]** against MA guidance before stating this in the demo.

### 3.5 Accepted proof (configurable; used to tell the member what to send)

| Path | Examples of acceptable proof |
| --- | --- |
| Employer wages | Two recent pay stubs (photos are fine), employer letter |
| Gig / self-employed | Earnings summary screenshot from the app for the month, bank statement showing deposits, 1099, self-employment ledger plus signed attestation |
| Volunteering | Letter or log from the organization with hours and a contact |
| Job training | Enrollment or attendance letter from the program |
| School | Enrollment verification letter showing half-time or more |
| Exemption | Depends on type: child's birth certificate or school record, doctor's note, treatment program letter, SNAP/TAFDC notice |

When documents aren't reasonably available, the agent offers an **attestation** (the member states the facts, signed) and flags the case. **[DEFAULT]**

---

## 4. Requirements (EARS format)

### 4.1 Channels and entry

- R1. WHEN a member sends an SMS to the MassHelp number, THE SYSTEM SHALL reply by SMS within 10 seconds for text-only messages and 20 seconds for messages with images.
- R2. WHEN a member calls the MassHelp number, THE SYSTEM SHALL answer through Vapi and begin speaking within 1.5 seconds of the member finishing each utterance (p50 target; measure it).
- R3. THE SYSTEM SHALL NOT initiate any call or SMS except as a direct reply within an active conversation, or a confirmation message the member was told about during that conversation.
- R4. WHEN a member texts STOP, THE SYSTEM SHALL stop messaging that number (Twilio handles STOP natively; the app must also mark the case as opted out and not send).

### 4.2 Identity

- R5. WHEN a conversation starts, THE SYSTEM SHALL look up the member by the caller or sender phone number in the member store.
- R6. IF the phone number matches a member, THEN THE SYSTEM SHALL ask for date of birth and SHALL NOT reveal any member data or case details until it matches.
- R7. IF the phone number doesn't match, THEN THE SYSTEM SHALL ask for the MassHealth ID and date of birth, and match on both.
- R8. IF identity fails 3 times, THEN THE SYSTEM SHALL stop, give the MassHealth customer service number (1-800-841-2900), and end the conversation politely.
- R9. THE SYSTEM SHALL NEVER ask for, store, or repeat a Social Security number, bank account number, or card number. IF the member offers one, THEN THE SYSTEM SHALL tell them it isn't needed and SHALL redact it from stored transcripts.

### 4.3 Language

- R10. THE SYSTEM SHALL use the member's preferred language from their record as the starting language.
- R11. WHEN the member writes or speaks in a different language or asks to switch, THE SYSTEM SHALL switch for all later messages, including SMS confirmations.
- R12. THE SYSTEM SHALL fill the PDF form in English regardless of conversation language.
- R13. Every agent message SHALL be plain language: short sentences, no jargon, no rule citations to the member. Voice replies SHALL be at most about 2 sentences per turn unless reading back answers.

### 4.4 Interview and eligibility

- R14. WHEN identity is confirmed, THE SYSTEM SHALL explain in 1 to 2 sentences why verification is needed (new rule starting January 1, 2027) and that it can be done right now on this channel.
- R15. THE SYSTEM SHALL screen exemptions before asking about work, hours, or income.
- R16. IF an exemption likely applies, THEN THE SYSTEM SHALL skip work questions and move to collecting exemption proof.
- R17. OTHERWISE THE SYSTEM SHALL ask about income first (fewest questions), then hours, then school, then combinations.
- R18. THE SYSTEM SHALL record every fact the member gives as a structured answer with its source (`voice`, `sms`, `document`) and the message it came from.
- R19. THE SYSTEM SHALL determine "likely meets", "likely exempt", "likely does not meet", or "needs more info" **only** by calling the deterministic rules engine. The LLM SHALL NOT state an outcome the engine didn't return.
- R20. IF the engine returns "likely does not meet", THEN THE SYSTEM SHALL check whether another month or another path could work, and if not, explain honestly, give the MassHealth number, and suggest the Health Connector as an alternative source of coverage.

### 4.5 Documents

- R21. WHEN a member sends an image by MMS, THE SYSTEM SHALL download it, store it, and extract the relevant fields (document type, name, period, gross and net amounts, hours, employer or platform) with a vision-capable model, returning structured JSON.
- R22. THE SYSTEM SHALL compare extracted amounts with what the member said. IF they differ by more than 10%, THEN THE SYSTEM SHALL ask the member about it rather than silently picking one.
- R23. IF the image is unreadable, THEN THE SYSTEM SHALL ask for a new photo with one concrete tip (lighting, flat surface, whole page in frame).
- R24. WHEN a call needs a document, THE SYSTEM SHALL tell the member it will text them, then send an SMS asking for the photo, so the case continues on SMS (G3).
- R25. IF the member says they don't have the requested document, THEN THE SYSTEM SHALL offer the alternatives from the rules config for that path.

### 4.6 Form, consent, submission

- R26. WHEN the engine returns "likely meets" or "likely exempt" and required proof is collected (or an attestation is accepted), THE SYSTEM SHALL generate a filled PDF.
- R27. BEFORE submitting, THE SYSTEM SHALL read back every filled field in plain language and ask the member to confirm or correct.
- R28. THE SYSTEM SHALL submit only after an explicit yes to a consent question naming what will be sent and to whom. The consent text, the member's reply, and a timestamp SHALL be stored.
- R29. WHEN submission succeeds, THE SYSTEM SHALL text the member a confirmation with the mock receipt number and a link to (and where supported, an MMS attachment of) the PDF.
- R30. THE SYSTEM SHALL support `DEMO_FIXED_PDF=path`, which makes the form tool return that file instead of generating one, for a deterministic demo.
- R31. Generated PDFs SHALL be watermarked "SAMPLE - NOT FOR SUBMISSION".

### 4.7 Safety and guardrails

- R32. In the first message of every conversation, THE SYSTEM SHALL say it is an automated assistant and not MassHealth.
- R33. WHEN asked "is this a scam?" or similar, THE SYSTEM SHALL explain that MassHelp never calls first and never asks for SSN or bank info, and give the official MassHealth number so they can check independently.
- R34. THE SYSTEM SHALL decline off-topic requests briefly and steer back, and SHALL hand off to MassHealth's number for anything it can't help with (appeals, coverage decisions, complaints).
- R35. THE SYSTEM SHALL NEVER promise coverage will be kept.
- R36. IF the LLM returns a refusal or an error, THEN THE SYSTEM SHALL send a short, safe fallback message ("Sorry, I had trouble with that. Can you say it another way?") and log the event. Don't drop the conversation.
- R37. Raw audio SHALL NOT be stored by the app. Transcripts are stored with SSN-like and card-like patterns redacted.

---

## 5. Architecture

```
            ┌──────────────┐  SMS/MMS webhook   ┌─────────────────────────────────────────┐
 Member ───▶│   Twilio     │ ─────────────────▶ │                FastAPI app               │
  phone     │  (SMS/MMS)   │ ◀───── REST send ─ │                                          │
            └──────────────┘                    │  channels/sms.py     channels/voice.py   │
            ┌──────────────┐  OpenAI-style      │        │                   │             │
 Member ───▶│    Vapi      │  /chat/completions │        └──────┬────────────┘             │
  phone     │ (STT + TTS,  │ ─────────────────▶ │               ▼                          │
            │  telephony)  │ ◀─── SSE stream ── │        agent/runner.py  (channel-agnostic)│
            └──────────────┘                    │         │   Claude API + tool loop       │
                                                │         ▼                                │
                                                │   tools/  ── rules engine (pure Python)  │
                                                │           ── docs (vision extraction)    │
                                                │           ── forms (PDF fill)            │
                                                │           ── masshealth_mock             │
                                                │           ── messaging (send SMS)        │
                                                │         │                                │
                                                │   store/ SQLite (SQLModel)               │
                                                └─────────────────────────────────────────┘
```

### 5.1 Stack **[DEFAULT]**

- Python 3.12, FastAPI, Uvicorn
- `anthropic` (official Python SDK) for all LLM calls
- SQLite through SQLModel (one file, `masshelp.db`)
- `twilio` Python SDK
- `pypdf` to fill an existing AcroForm PDF; `reportlab` to generate the mock form and the watermark
- `pydantic-settings` for config, `pyyaml` for rules
- `pytest`, `hypothesis` (property-based tests), `respx` or `pytest-httpx` for HTTP mocks
- `uv` for dependency management
- Local run with an **ngrok** (or Cloudflare Tunnel) public URL for the Twilio and Vapi webhooks. A Dockerfile is a stretch goal.

### 5.2 LLM configuration

- Conversation model: **`claude-haiku-5-5`**, for latency. Configurable by `MASSHELP_MODEL`.
- Escalation model (optional, configurable by `MASSHELP_HEAVY_MODEL`): `claude-sonnet-5-5`, for document extraction if Haiku is unreliable on photos. Start with Haiku for everything and switch only if tests show it's needed.
- Request settings for conversation turns:
  - Stream every response (`client.messages.stream(...)`).
  - `thinking={"type": "disabled"}` and `output_config={"effort": "low"}`. On Haiku 5.5, disabled thinking is accepted only at effort `high` or below, which `low` satisfies.
  - Do **not** send `temperature`, `top_p`, or `top_k`; current API versions reject them.
  - Do **not** prefill an assistant message; current models reject it.
  - `tool_choice` stays `auto`. Use `strict: true` on tool definitions so tool inputs are schema-valid.
  - Prompt caching: put `cache_control` on the end of the static system prompt plus tool list. Keep anything dynamic (date, member facts, case state) **after** the cache breakpoint, in a per-turn block. Check `usage.cache_read_input_tokens` is above 0 on the second turn.
  - `max_tokens`: 1024 for voice turns, 2048 for SMS turns.
  - Handle `stop_reason == "refusal"` per R36. Haiku has no server-side fallback, so handle it in code.
  - Parse tool inputs with `json.loads` (or the SDK's parsed object), never by string matching.
- Document extraction: a separate, non-streaming call with the image as a base64 `image` block and structured output (`output_config.format` with a JSON schema) for the extraction result.

### 5.3 Channel adapters

Both adapters convert a channel event into a call to `AgentRunner.handle(case_id, channel, user_input) -> AsyncIterator[str]` and send the text back their own way.

#### SMS (Twilio) `POST /twilio/sms`

1. Validate the `X-Twilio-Signature` header with the auth token. Reject with 403 if invalid (skippable with `TWILIO_VALIDATE=false` for local tests only).
2. Read `From`, `Body`, `NumMedia`, `MediaUrl{i}`, `MediaContentType{i}`.
3. Respond **immediately** with empty TwiML (`<Response/>`), status 200. Twilio times out webhooks at 15 seconds, and image turns can be slow.
4. In a background task: download media (Twilio media URLs may require HTTP basic auth with the account SID and token **[VERIFY]**), store files, run the agent turn, collect the full streamed text, and send it with the Twilio REST API.
5. Split replies over about 600 characters into multiple messages at sentence boundaries.
6. Serialize turns per phone number (an asyncio lock keyed by number) so two quick texts don't race.

#### Voice (Vapi custom LLM) `POST /vapi/chat/completions`

Vapi's "Custom LLM" provider sends OpenAI Chat Completions-style requests to `{CUSTOM_LLM_URL}/chat/completions` and expects an OpenAI-style streaming response. **[VERIFY]** the exact payload against current Vapi docs before building; known from the docs:

- POST to `/chat/completions` under the configured base URL. Configure the base URL as `https://<public-host>/vapi`.
- Streaming is recommended. Respond with `text/event-stream`, `data: {chat.completion.chunk JSON}` lines, then `data: [DONE]`.
- Optional auth: Vapi can send an API key in the `Authorization` header. Set `VAPI_SECRET` and reject requests without it.

Behavior:

1. Parse the body. Get the conversation `messages` (OpenAI format) and the call object. The caller's number is expected at `call.customer.number` and the call ID at `call.id` **[VERIFY]**.
2. Map `call.id` to the case (look up by caller number on the first request of a call).
3. Take the latest user message as `user_input`. Our own case transcript in SQLite is the source of truth for history, not Vapi's `messages`, so history stays consistent across channels.
4. Run the agent turn. Tool calls are executed **inside our server** (Claude tool loop). Only the final spoken text streams to Vapi, as OpenAI-style chunks with `choices[0].delta.content`.
5. Do not expose our tools to Vapi as OpenAI function calls.
6. To keep latency low when a tool call is needed, the system prompt tells the model to say a short filler first ("One second while I check that.") **in the same response** before calling a slow tool. Stream that text to Vapi right away, then continue the stream after the tool loop.
7. Ending the call: configure Vapi's assistant end-call phrases (for example "Goodbye from MassHelp") **[VERIFY]**, and have the agent say that phrase when the conversation is done.
8. In the Vapi assistant config: set the first message to the greeting with the AI disclosure (R32), choose a TTS voice that supports Spanish, and enable the transcriber's multilingual mode if available **[VERIFY]**.

### 5.4 Agent runner

`agent/runner.py`:

```python
class AgentRunner:
    async def handle(self, case_id: str, channel: Literal["sms", "voice"], user_input: UserInput) -> AsyncIterator[str]:
        """Append user input to the transcript, run Claude with tools until end_turn,
        stream assistant text out, persist assistant messages and tool results."""
```

- Builds the request from: static system prompt (cached) + tool definitions (cached) + per-turn context block (today's date, channel, member summary, case state and collected answers, language) + transcript.
- Transcript storage keeps the full Claude `content` blocks (text, tool_use, tool_result) so history replays exactly. Only append; never edit earlier turns.
- The tool loop runs at most 6 tool rounds per user turn, then stops with a safe message.
- Channel-specific style comes from the per-turn context: voice means very short, no lists, no URLs, spell out numbers and dates; SMS means short paragraphs and numbered lists are fine.
- `DEMO_TODAY` env var overrides "today" (for example `2026-12-01`) so the demo date story is consistent.

### 5.5 Tools exposed to Claude

All tools are plain Python functions with JSON schemas (`strict: true`, `additionalProperties: false`). They return JSON. Tools that need member data refuse unless `case.identity_verified` is true.

| Tool | Input | Output | Notes |
| --- | --- | --- | --- |
| `verify_identity` | `date_of_birth` (YYYY-MM-DD), optional `masshealth_id` | `{verified: bool, attempts_left}` | Enforces R6 to R8 |
| `get_case_status` | none | Member first name, preferred language, what MassHealth requested, deadline, answers so far, missing items | The model calls this after verifying |
| `record_answers` | list of `{field, value, source_message_id?}` | Updated answers | `field` is an enum (see 6.3) |
| `evaluate_requirement` | optional `month` (YYYY-MM) | `{status, path, reasons[], missing[], proof_needed[]}` | Calls the rules engine; the only source of outcomes (R19) |
| `request_document` | `doc_type` | `{sms_sent: bool, instructions}` | On voice, texts the member what to send (R24) |
| `get_documents` | none | Extracted data for each received document, with mismatch flags | |
| `prepare_form` | none | `{pdf_id, fields: {label: value}}` | Builds the PDF; respects `DEMO_FIXED_PDF`. Returns fields for read-back |
| `record_consent` | `consent_text`, `member_reply` | `{consent_id}` | Required before submit (R28) |
| `submit_to_masshealth` | `pdf_id`, `consent_id` | `{receipt_number, submitted_at}` | Mock. Rejects without a valid consent |
| `send_confirmation_sms` | `receipt_number`, `pdf_id` | `{sent: bool}` | Text plus PDF link or MMS media |
| `set_language` | `language` (BCP-47) | ok | R11 |
| `handoff_to_human` | `reason` | `{phone, message}` | Returns MassHealth customer service info and logs the reason |

### 5.6 Rules engine (pure, deterministic)

`rules/engine.py`, no I/O and no LLM:

```python
def evaluate(facts: MemberFacts, month: YearMonth, rules: RulesConfig) -> Evaluation
```

- `Evaluation.status` is one of `LIKELY_EXEMPT`, `LIKELY_MEETS`, `LIKELY_DOES_NOT_MEET`, `NEEDS_MORE_INFO`.
- Order: age and group check, then exemptions, then income, then school, then hours, then combination.
- Returns `path` (which rule was satisfied), human-readable `reasons`, `missing` facts, and `proof_needed` (from the config).
- Hours from weekly figures: `weekly_hours × 4.33`, rounded down. Store both.
- Thresholds, exemption list, and proof types come from `rules/masshealth_rules.yaml`.

### 5.7 Mock MassHealth service

`masshealth_mock/service.py` behind an interface (`MassHealthClient`) so it can be swapped later:

- `get_member_by_phone(phone)`, `get_member_by_id(mh_id)`
- `get_open_requests(member_id)`: what verification is due and the deadline
- `submit_verification(member_id, packet) -> Receipt` with receipt numbers like `MOCK-RCPT-12345`
- Seeded from `seed/members.yaml`. Phone numbers for demo members come from env (`DEMO_PHONE_MARIA`, `DEMO_PHONE_CARLOS`, ...) so the team's real phones can stand in.

### 5.8 Forms

`forms/`:

- **[DEFAULT]** Target the MassHealth **Job Update form (JU-1)**: English at https://www.mass.gov/doc/masshealth-job-update-form-0/download and Spanish at https://www.mass.gov/doc/masshealth-job-update-form-spanish/download. First task: download it and check whether it has fillable AcroForm fields (`pypdf.PdfReader(...).get_fields()`).
  - If fillable: map our answer fields to its form field names in `forms/ju1_mapping.yaml` and fill with `pypdf`.
  - If not fillable, or the form doesn't fit the new rule well: generate a one-to-two page **"MassHelp Work Requirement Verification (SAMPLE)"** PDF with `reportlab`, containing member name, MassHealth ID, month, path, each fact with its source, documents attached, attestation text, consent timestamp. It must be honest that it is a mock.
- Every PDF gets the SAMPLE watermark (R31).
- PDFs are served at `GET /files/{token}`, where the token is random and expires after 7 days, so the SMS link works without login.

### 5.9 Data model (SQLite)

- `Member`: id, masshealth_id, first_name, last_name, dob, phone_e164, preferred_language, program ("CarePlus"), seed facts (for demo: employer, etc.)
- `Case`: id, member_id (nullable until identified), phone_e164, status (`open`, `identity_pending`, `in_progress`, `ready_to_submit`, `submitted`, `closed`), identity_verified, identity_attempts, language, request_type, deadline, opted_out, created_at, updated_at
- `Message`: id, case_id, channel, role (`user`, `assistant`), content_json (full Claude content blocks), redacted_text, created_at
- `Answer`: id, case_id, field, value_json, source (`voice`, `sms`, `document`), message_id, created_at (latest per field wins; history kept)
- `Document`: id, case_id, media_path, content_type, doc_type, extracted_json, mismatch_flag, created_at
- `Consent`: id, case_id, consent_text, member_reply, channel, created_at
- `Submission`: id, case_id, pdf_path, receipt_number, packet_json, created_at
- `Event`: id, case_id, type, payload_json, created_at (audit log: tool calls, refusals, errors, latency)

One open case per member at a time. SMS and voice from the same number resolve to the same open case (G3).

---

## 6. Prompting

### 6.1 System prompt outline (`agent/prompts/system.md`)

1. Role: "You are MassHelp, a free automated helper for MassHealth members. You are not MassHealth and you don't make decisions."
2. Goal: help the member prove they meet the work rule or an exemption, and submit their response, in as few questions as possible.
3. Principles from `VISION.md`: assume the person qualifies; plain language first; one question at a time; never collect SSN or bank info; never promise outcomes; say "likely" and "MassHealth makes the final decision".
4. Process: verify identity, explain briefly, exemptions first, then income, then hours, collect proof, prepare form, read back, consent, submit, confirm.
5. Tool rules: always use `evaluate_requirement` for outcomes; call `record_answers` as soon as a fact is given; say a short filler line before slow tools on voice.
6. Policy facts: injected from the rules config at startup (thresholds, exemptions, proof types), so the prompt and the engine never disagree.
7. Style by channel (voice vs SMS) and language behavior.
8. Safety scripts: scam question, off-topic, distress (if a member mentions a medical emergency, tell them to call 911), handoff.

### 6.2 Few-shot

Include 2 short example exchanges (one voice, one SMS) in the system prompt: the gig worker without pay stubs, and the photo-of-paystub path. Keep them short; they are cached anyway.

### 6.3 Answer fields (enum)

`month`, `is_exempt_claimed`, `exemption_type`, `employment_type` (`employee`, `self_employed`, `gig`, `none`), `employer_or_platform`, `weekly_hours`, `monthly_hours`, `monthly_gross_income`, `monthly_expenses`, `monthly_net_income`, `is_seasonal`, `school_name`, `school_enrollment` (`full_time`, `half_time`, `less_than_half`), `volunteer_org`, `volunteer_hours`, `training_program`, `training_hours`, `health_insurance_offered`, `expected_annual_income`, `attestation_accepted`.

---

## 7. Configuration (env)

| Var | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API |
| `MASSHELP_MODEL` | Default `claude-haiku-5-5` |
| `MASSHELP_HEAVY_MODEL` | Optional, e.g. `claude-sonnet-5-5` for document extraction |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | SMS |
| `TWILIO_VALIDATE` | `true` by default |
| `VAPI_SECRET` | Expected value of the Authorization header from Vapi |
| `PUBLIC_BASE_URL` | ngrok URL, used for PDF links and MMS media |
| `DATABASE_URL` | Default `sqlite:///masshelp.db` |
| `DEMO_TODAY` | Optional date override |
| `DEMO_FIXED_PDF` | Optional path; forces the form output |
| `DEMO_PHONE_*` | Seed phone numbers for demo members |

Provide `.env.example`. Never commit real secrets.

---

## 8. Repo layout

```
/
├── .kiro/                  # committed; specs, steering, hooks (section 11)
├── VISION.md
├── SPEC.md                 # this file
├── README.md               # setup, run, demo instructions, Kiro write-up link
├── pyproject.toml
├── .env.example
├── masshelp/
│   ├── main.py             # FastAPI app, routes
│   ├── config.py
│   ├── channels/
│   │   ├── sms.py
│   │   └── voice.py        # Vapi OpenAI-style SSE adapter
│   ├── agent/
│   │   ├── runner.py
│   │   ├── tools.py        # tool schemas + dispatch
│   │   └── prompts/system.md
│   ├── rules/
│   │   ├── engine.py
│   │   ├── models.py
│   │   └── masshealth_rules.yaml
│   ├── docs/extract.py     # vision extraction
│   ├── forms/
│   │   ├── fill.py
│   │   ├── mock_form.py
│   │   └── ju1_mapping.yaml
│   ├── masshealth_mock/service.py
│   ├── store/models.py, db.py
│   └── util/redact.py, phone.py
├── seed/members.yaml
├── scripts/
│   ├── chat_cli.py         # talk to the agent in a terminal, as SMS or voice style
│   └── seed_db.py
└── tests/
    ├── test_rules_engine.py
    ├── test_rules_properties.py   # hypothesis
    ├── test_redact.py
    ├── test_sms_webhook.py
    ├── test_vapi_stream.py
    ├── test_forms.py
    └── conversations/             # scripted end-to-end runs with a fake LLM
```

**`scripts/chat_cli.py` is required.** It lets the team and Kiro test the whole agent without Twilio or Vapi: `uv run scripts/chat_cli.py --phone +16175550101 --channel voice`, with `/image path.jpg` to simulate MMS.

---

## 9. Demo scenarios (acceptance tests)

Seed data must make both of these run exactly as written. `DEMO_TODAY=2026-12-01`.

### 9.1 Maria, voice, gig worker without pay stubs

Seed: Maria Santos, DOB 1992-06-04, MassHealth ID `MH-DEMO-000123`, preferred language English, CarePlus, open request "work requirement verification", deadline 2026-12-31.

1. Maria calls. Agent greets, discloses it's automated and not MassHealth.
2. Agent recognizes her number, asks DOB, she gives it, verified.
3. Agent explains in 2 sentences: new rule from January 1, 2027, needs to confirm work or income, can do it now in a few minutes.
4. Exemption screening (child 13 or under, pregnancy, health condition or treatment, SNAP/TAFDC): all no.
5. Income: she drives for a delivery app, about 25 hours a week, about $1,150 before gas, about $900 after. Engine: `LIKELY_MEETS` by income ($900 ≥ $580). Hours path also met (25 × 4.33 = 108).
6. She has no pay stubs. Agent says that's fine and texts her what to send: a screenshot of her monthly earnings in the app.
7. Agent prepares the form, reads it back, asks for consent to submit for her. She says yes.
8. **[DEFAULT]** Submission waits until the screenshot arrives, or she can choose to submit now with an attestation. For the demo: she sends the screenshot by text while still on the call or right after, the agent confirms it was received and the amount matches, then submits.
9. She gets an SMS confirmation with the receipt number and PDF.

### 9.2 Carlos, SMS, Spanish, paper paystubs

Seed: Carlos (last name of your choice), Spanish preferred, full-time landscaping employee, open request, deadline 2026-12-31.

1. Carlos texts "Hola" (or "Recibí una carta de MassHealth").
2. Agent replies in Spanish, disclosure, asks DOB. Verified.
3. Agent explains and screens exemptions briefly (numbered list in one text is fine).
4. Carlos says he works full time for a landscaping company. Agent asks for two recent paystubs.
5. He says they're paper. Agent says photos are fine, with one tip about lighting.
6. He texts 2 photos. Agent extracts employer, period, hours, and pay; confirms it meets the rule.
7. Agent prepares the form (in English), summarizes it in Spanish, asks for consent, he replies "Sí".
8. Submitted, confirmation text in Spanish with receipt and PDF.

Include 2 sample paystub images and 1 sample earnings screenshot in `seed/sample_docs/` (synthetic, clearly fake, no real brand logos) for testing and the demo.

### 9.3 Extra branches to cover in tests (not in the video)

- Parent of a 10-year-old: exemption path, no hours asked.
- Half-time student: school path.
- $300 income plus 50 volunteer hours: combination path (300 / 7.25 ≈ 41 + 50 = 91 ≥ 80).
- Lost job, no hours: honest "likely does not meet", MassHealth number, Health Connector suggestion.
- "Is this a scam?": safety script.
- Member offers SSN: refused and redacted.
- Unknown phone number: MassHealth ID plus DOB path.
- Mismatch: says $900, screenshot shows $600: agent asks.

---

## 10. Testing

- **Rules engine unit tests**: every path and exemption, edge values ($579.99, $580.00, 79 hours, 80 hours, age 18/19/64/65).
- **Property-based tests (Hypothesis)**, required because Kiro judging asks about PBT:
  - Any facts with `monthly_net_income >= 580` and no disqualifying age give `LIKELY_MEETS` or `LIKELY_EXEMPT`.
  - If any exemption is true, the result is `LIKELY_EXEMPT` regardless of hours or income.
  - Monotonic: increasing hours or income never turns a "meets" result into "does not meet".
  - Combination: `income/7.25 + volunteer + training + work hours >= 80` implies "meets".
  - Redaction: any 9-digit SSN-shaped string or 13 to 19 digit card-shaped string inside random text is removed.
- **Adapter tests**: Twilio signature validation, immediate empty TwiML, media download path; Vapi SSE format (valid chunks, ends with `[DONE]`, filler text arrives before tool results).
- **Conversation tests** with a fake LLM client that replays scripted tool calls, so CI doesn't need an API key. One optional live test suite (`-m live`) that runs the two demo scenarios against the real Claude API.
- **Latency logging**: log time to first token per voice turn in `Event`; print p50 and p95 in `scripts/latency_report.py`.

---

## 11. Kiro usage plan (judged)

Build with Kiro and keep evidence in `/.kiro`:

- **Spec**: feed this file to Kiro to generate `.kiro/specs/masshelp/requirements.md`, `design.md`, `tasks.md`, and execute tasks from there. Keep the EARS requirement IDs (R1 to R37) so tasks trace to them.
- **Steering** (`.kiro/steering/`):
  - `product.md`: mission, principles, non-goals (from `VISION.md`).
  - `tech.md`: stack, LLM settings from 5.2 (Haiku, streaming, no temperature, no prefill, caching).
  - `structure.md`: repo layout from section 8.
  - `plain-language.md`: rules for every member-facing string.
  - `policy.md`: the rule thresholds and the "rules engine decides, never the LLM" constraint.
- **Hooks** (`.kiro/hooks/`):
  - On save in `masshelp/rules/**`: run `pytest tests/test_rules_engine.py tests/test_rules_properties.py`.
  - On save in `masshelp/agent/prompts/**`: run the conversation tests.
  - On save in `masshelp/rules/masshealth_rules.yaml`: regenerate the policy section of the system prompt and the steering `policy.md`.
  - Pre-commit-style hook: scan the diff for secrets and real-looking SSNs.
- **MCP**: consider connecting a Twilio or docs MCP server for looking up API details while building; note what was used.
- **PBT**: section 10.
- Keep a running `KIRO_NOTES.md` as you go (which tool, what worked, what didn't). The submission write-up is built from it.

---

## 12. Task plan

Ordered so something demoable exists as early as possible. Each task lists the requirements it covers.

1. **Scaffold**: `pyproject.toml`, FastAPI app with `/health`, config, SQLite models, seed script, `.env.example`, README run steps. Steering docs in `.kiro/steering/`.
2. **Rules engine + config + tests + PBT** (R15 to R20, section 3). No LLM yet.
3. **Mock MassHealth service + seed members** (5.7).
4. **Agent runner + tools + system prompt + `chat_cli.py`** (R5 to R20, R32 to R36). Demo 9.1 should work in the terminal by the end of this task, minus documents and PDF.
5. **Forms**: download JU-1, check whether it's fillable, implement fill or mock form, watermark, `/files/{token}` (R26, R30, R31).
6. **Consent + mock submit + confirmation** (R27 to R29).
7. **SMS adapter** with Twilio (R1, R4, 5.3). Demo 9.2 text-only works on a real phone.
8. **Document extraction** from MMS (R21 to R25). Demo 9.2 with photos works.
9. **Voice adapter** with Vapi custom LLM, SSE streaming, filler lines, end-call phrase (R2, 5.3). Demo 9.1 works on a real call.
10. **Cross-channel continuity**: call then SMS photo on the same case (G3, R24).
11. **Redaction and safety tests** (R9, R37, R33).
12. **Latency pass**: measure time to first token, tune prompt length, caching, `max_tokens`, filler lines.
13. **Demo hardening**: `DEMO_TODAY`, `DEMO_FIXED_PDF`, reset script (`scripts/reset_demo.py`), sample docs.
14. **README + Kiro write-up** for submission.

Stretch (only after 1 to 14): Dockerfile and a cloud deploy; Haitian Creole and Portuguese testing; reminder texts for members who opted in during a conversation; a read-only case viewer page for judges.

---

## 13. Known risks and open items

- **Twilio SMS registration.** US carriers block SMS from unregistered 10DLC numbers, and A2P 10DLC or toll-free verification can take days. Check today whether the account can text the team's phones. Fallbacks: trial account to verified numbers, or show the SMS flow through `chat_cli.py` in the video. **[VERIFY]**
- **Twilio MMS with PDF.** Sending a PDF as MMS media isn't reliable on all carriers. Always include the link; attach the PDF as media only as a bonus.
- **Vapi payload details** (5.3) are marked **[VERIFY]**. Build a tiny echo endpoint first and log a real request before writing the adapter.
- **Voice latency.** Tool rounds add delay. Mitigate with filler lines, Haiku, low effort, short prompts, and caching. If a turn regularly exceeds 2 seconds, move `record_answers` to a background write and keep `evaluate_requirement` fast (it's pure Python).
- **Policy uncertainty.** MA hasn't finalized rules. Everything policy-specific is in `masshealth_rules.yaml` and agent language always says "likely".
- **Submission timing in 9.1.** The default is to wait for proof before submitting; confirm with the team.
- **Form choice** (5.8) is a default pending a look at the JU-1 PDF.
