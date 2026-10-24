# Requirements Document

## Introduction

MassHelp is a headless AI assistant that helps MassHealth members prove they meet the new Medicaid work and community engagement rule, so they do not lose coverage over paperwork. A member calls or texts the MassHelp number, and the agent confirms who they are, explains what is needed in plain language and in their language, finds the shortest path to compliance (exemption first, then income, then hours), collects proof, autofills the verification form as a PDF, and submits it with explicit consent. There is no web or mobile frontend: the only surfaces are SMS through Twilio and voice through Vapi. All MassHealth systems are mocks with dummy data, and nothing is submitted to MassHealth for real.

## Glossary

- **Member**: A MassHealth member who contacts MassHelp. In the MVP, a seeded record in the mock member store.
- **Case**: One open verification effort for a member. SMS and voice from the same phone number resolve to the same open case. It holds identity status, language, answers, documents, consent, and submission.
- **Rules engine**: Pure, deterministic Python (`masshelp/rules/engine.py`) that evaluates a member's facts for a month against `masshelp/rules/masshealth_rules.yaml`. No I/O and no LLM. The only source of outcomes.
- **Likely meets** (`LIKELY_MEETS`): The facts satisfy at least one path: hours, school, income, seasonal income, or a combination.
- **Likely exempt** (`LIKELY_EXEMPT`): An exemption likely applies. Work questions are skipped and exemption proof is collected.
- **Likely does not meet** (`LIKELY_DOES_NOT_MEET`): The known facts satisfy no path and no exemption.
- **Needs more info** (`NEEDS_MORE_INFO`): Facts are missing, so the engine cannot reach one of the other outcomes yet.
- **Attestation**: A signed statement in which the member states the facts. Offered when documents are not reasonably available. The case is flagged when one is used.
- **CarePlus**: The MassHealth coverage type for ACA expansion adults aged 19 to 64, the group the work rule applies to.
- **Vapi**: Voice platform that handles telephony, speech to text, and text to speech. It calls MassHelp as a custom LLM through an OpenAI-style `/chat/completions` endpoint with SSE streaming.
- **Twilio**: SMS and MMS provider. It sends inbound messages to a MassHelp webhook and delivers replies sent through its REST API.
- **Health Connector**: The Massachusetts Health Connector, the state's health insurance marketplace. Suggested as another source of coverage when a member likely does not meet the rule.

## Goals

- **G1.** A member can complete a work requirement verification entirely by phone call.
- **G2.** A member can complete it entirely by SMS, including sending photos of documents.
- **G3.** A case started on one channel continues on the other (for example, call first, then text a photo).
- **G4.** Eligibility logic is deterministic code, not LLM judgment. The LLM gathers facts and explains; the rules engine decides "likely meets".
- **G5.** English and Spanish work end to end. Other languages work best effort through the LLM.
- **G6.** The two demo scenarios in Requirement 8 run reliably and repeatably with seeded data.

## Non-goals

- No outbound contact. The agent never calls or texts first. The member always starts. Reminders and outreach are future work.
- No real MassHealth integration, real member data, or real submission.
- No web UI, navigator console, or admin dashboard.
- No eligibility decisions. The agent always says "likely meets" and "MassHealth makes the final decision."
- No legal advice and no appeals handling. The agent may give the MassHealth phone number and suggest legal aid.
- No collection of SSN, bank account, or card numbers, ever.

## Requirements

### Requirement 1: Channels and entry

**User Story:** As a member, I want to call or text one MassHelp number and get a quick reply, so that I can handle verification from any phone without an app or internet.

#### Acceptance Criteria

1. **R1** WHEN a member sends an SMS to the MassHelp number, THE SYSTEM SHALL reply by SMS within 10 seconds for text-only messages and within 20 seconds for messages with images.
2. **R2** WHEN a member calls the MassHelp number, THE SYSTEM SHALL answer through Vapi and begin speaking within 1.5 seconds of the member finishing each utterance (p50 target, measured).
3. **R3** THE SYSTEM SHALL NOT initiate any call or SMS except as a direct reply within an active conversation, or as a confirmation message the member was told about during that conversation.
4. **R4** WHEN a member texts STOP, THE SYSTEM SHALL stop messaging that number. Twilio handles STOP natively; THE SYSTEM SHALL also mark the case as opted out and SHALL NOT send to it.

### Requirement 2: Identity

**User Story:** As a member, I want MassHelp to confirm who I am before it shares anything, so that no one else can see or act on my case.

#### Acceptance Criteria

1. **R5** WHEN a conversation starts, THE SYSTEM SHALL look up the member by the caller or sender phone number in the member store.
2. **R6** IF the phone number matches a member, THEN THE SYSTEM SHALL ask for date of birth and SHALL NOT reveal any member data or case details until it matches.
3. **R7** IF the phone number does not match a member, THEN THE SYSTEM SHALL ask for the MassHealth ID and date of birth, and SHALL match on both.
4. **R8** IF identity verification fails 3 times, THEN THE SYSTEM SHALL stop, give the MassHealth customer service number (1-800-841-2900), and end the conversation politely.
5. **R9** THE SYSTEM SHALL NEVER ask for, store, or repeat a Social Security number, bank account number, or card number. IF the member offers one, THEN THE SYSTEM SHALL tell them it is not needed and SHALL redact it from stored transcripts.

### Requirement 3: Language

**User Story:** As a member who may prefer Spanish or another language, I want MassHelp to talk with me in my language and in plain words, so that I understand what is needed.

#### Acceptance Criteria

1. **R10** THE SYSTEM SHALL use the member's preferred language from their record as the starting language.
2. **R11** WHEN the member writes or speaks in a different language, or asks to switch, THE SYSTEM SHALL switch to that language for all later messages, including SMS confirmations.
3. **R12** THE SYSTEM SHALL fill the PDF form in English regardless of the conversation language.
4. **R13** THE SYSTEM SHALL write every agent message in plain language: short sentences, no jargon, and no rule citations to the member. WHILE on a voice call, THE SYSTEM SHALL keep replies to at most about 2 sentences per turn, unless reading back answers.

### Requirement 4: Interview and eligibility

**User Story:** As a member who likely qualifies, I want to answer as few questions as possible and get an answer based on fixed rules, so that I finish quickly and can trust the result.

#### Acceptance Criteria

1. **R14** WHEN identity is confirmed, THE SYSTEM SHALL explain in 1 to 2 sentences why verification is needed (a new rule starting January 1, 2027) and that it can be done right now on this channel.
2. **R15** THE SYSTEM SHALL screen exemptions before asking about work, hours, or income.
3. **R16** IF an exemption likely applies, THEN THE SYSTEM SHALL skip work questions and move to collecting exemption proof.
4. **R17** IF no exemption likely applies, THEN THE SYSTEM SHALL ask about income first (fewest questions), then hours, then school, then combinations.
5. **R18** THE SYSTEM SHALL record every fact the member gives as a structured answer with its source (`voice`, `sms`, or `document`) and the message it came from.
6. **R19** THE SYSTEM SHALL determine "likely meets", "likely exempt", "likely does not meet", or "needs more info" only by calling the deterministic rules engine. THE LLM SHALL NOT state an outcome the engine did not return.
7. **R20** IF the engine returns "likely does not meet", THEN THE SYSTEM SHALL check whether another month or another path could work, and IF neither can, THEN THE SYSTEM SHALL explain honestly, give the MassHealth number, and suggest the Health Connector as an alternative source of coverage.

### Requirement 5: Documents

**User Story:** As a member with paper paystubs or only an app earnings screen, I want to send a photo by text, so that I can prove my income with what I actually have.

#### Acceptance Criteria

1. **R21** WHEN a member sends an image by MMS, THE SYSTEM SHALL download it, store it, and extract the relevant fields (document type, name, period, gross and net amounts, hours, employer or platform) with a vision-capable model, returning structured JSON.
2. **R22** THE SYSTEM SHALL compare extracted amounts with what the member said. IF they differ by more than 10%, THEN THE SYSTEM SHALL ask the member about it rather than silently picking one.
3. **R23** IF the image is unreadable, THEN THE SYSTEM SHALL ask for a new photo with one concrete tip (lighting, flat surface, or whole page in frame).
4. **R24** WHEN a call needs a document, THE SYSTEM SHALL tell the member it will text them, then send an SMS asking for the photo, so the case continues on SMS (G3).
5. **R25** IF the member says they do not have the requested document, THEN THE SYSTEM SHALL offer the alternatives from the rules config for that path.

### Requirement 6: Form, consent, submission

**User Story:** As a member, I want to hear what will be sent and say yes before anything is submitted, and then get a receipt, so that I stay in control and have proof that I responded.

#### Acceptance Criteria

1. **R26** WHEN the engine returns "likely meets" or "likely exempt" and the required proof is collected (or an attestation is accepted), THE SYSTEM SHALL generate a filled PDF.
2. **R27** BEFORE submitting, THE SYSTEM SHALL read back every filled field in plain language and ask the member to confirm or correct it.
3. **R28** THE SYSTEM SHALL submit only after an explicit yes to a consent question that names what will be sent and to whom. THE SYSTEM SHALL store the consent text, the member's reply, and a timestamp.
4. **R29** WHEN submission succeeds, THE SYSTEM SHALL text the member a confirmation with the mock receipt number and a link to the PDF, and where supported, an MMS attachment of the PDF.
5. **R30** WHERE `DEMO_FIXED_PDF=path` is set, THE SYSTEM SHALL make the form tool return that file instead of generating one, for a deterministic demo.
6. **R31** THE SYSTEM SHALL watermark every generated PDF "SAMPLE - NOT FOR SUBMISSION".

### Requirement 7: Safety and guardrails

**User Story:** As a member who is wary of scams and worried about my coverage, I want MassHelp to be honest about what it is and what it can do, so that I can trust it and know where to go for anything else.

#### Acceptance Criteria

1. **R32** THE SYSTEM SHALL say in the first message of every conversation that it is an automated assistant and not MassHealth.
2. **R33** WHEN asked "is this a scam?" or similar, THE SYSTEM SHALL explain that MassHelp never calls first and never asks for SSN or bank information, and SHALL give the official MassHealth number so the member can check independently.
3. **R34** THE SYSTEM SHALL decline off-topic requests briefly and steer back, and SHALL hand off to MassHealth's number for anything it cannot help with (appeals, coverage decisions, complaints).
4. **R35** THE SYSTEM SHALL NEVER promise that coverage will be kept.
5. **R36** IF the LLM returns a refusal or an error, THEN THE SYSTEM SHALL send a short, safe fallback message ("Sorry, I had trouble with that. Can you say it another way?"), log the event, and keep the conversation going.
6. **R37** THE SYSTEM SHALL NOT store raw audio. THE SYSTEM SHALL store transcripts only with SSN-like and card-like patterns redacted.

### Requirement 8: Demo scenarios

**User Story:** As the hackathon team, I want the two demo scenarios and the extra branches to run the same way every time from seeded data, so that the video and judging are reliable.

#### Acceptance Criteria

1. **D1** WHILE `DEMO_TODAY=2026-12-01` is set and seed data is loaded, THE SYSTEM SHALL run scenarios 9.1 and 9.2 exactly as written, every time (G6).
2. **D2** WHEN Maria Santos (DOB 1992-06-04, MassHealth ID `MH-DEMO-000123`, English, CarePlus, open "work requirement verification" request, deadline 2026-12-31) calls from her seeded number, THE SYSTEM SHALL greet her with the automated assistant disclosure, recognize her number, ask for her date of birth, and verify her. (9.1)
3. **D3** WHEN Maria is verified, THE SYSTEM SHALL explain in 2 sentences that a new rule starts January 1, 2027, that it needs to confirm work or income, and that this can be done now in a few minutes. (9.1)
4. **D4** WHEN Maria answers no to every exemption screen (child 13 or under, pregnancy, health condition or treatment, SNAP/TAFDC), THE SYSTEM SHALL move on to income questions. (9.1)
5. **D5** WHEN Maria says she drives for a delivery app about 25 hours a week and earns about $1,150 before gas and about $900 after, THE SYSTEM SHALL record those answers, and the engine SHALL return `LIKELY_MEETS` by income ($900 >= $580), with the hours path also met (25 x 4.33 = 108). (9.1)
6. **D6** WHEN Maria says she has no pay stubs, THE SYSTEM SHALL tell her that is fine and text her what to send: a screenshot of her monthly earnings in the app. (9.1)
7. **D7** THE SYSTEM SHALL prepare Maria's form, read it back, and ask for consent to submit for her. (9.1)
8. **D8** WHILE Maria's earnings screenshot has not arrived, THE SYSTEM SHALL hold submission unless she chooses to submit now with an attestation. WHEN the screenshot arrives by SMS during or right after the call, THE SYSTEM SHALL confirm it was received and the amount matches, then submit. [DEFAULT] (9.1)
9. **D9** WHEN Maria's submission succeeds, THE SYSTEM SHALL text her a confirmation with the receipt number and the PDF. (9.1)
10. **D10** WHEN Carlos (Spanish preferred, full-time landscaping employee, open request, deadline 2026-12-31) texts "Hola" or "Recibí una carta de MassHealth", THE SYSTEM SHALL reply in Spanish with the disclosure, ask for his date of birth, and verify him. (9.2)
11. **D11** WHEN Carlos is verified, THE SYSTEM SHALL explain the rule and screen exemptions briefly; a numbered list in one text is acceptable. (9.2)
12. **D12** WHEN Carlos says he works full time for a landscaping company, THE SYSTEM SHALL ask for two recent paystubs. (9.2)
13. **D13** WHEN Carlos says his paystubs are on paper, THE SYSTEM SHALL tell him photos are fine and give one tip about lighting. (9.2)
14. **D14** WHEN Carlos texts 2 paystub photos, THE SYSTEM SHALL extract employer, period, hours, and pay, and confirm through the engine that he meets the rule. (9.2)
15. **D15** THE SYSTEM SHALL prepare Carlos's form in English, summarize it in Spanish, ask for consent, and accept "Sí" as an explicit yes. (9.2)
16. **D16** WHEN Carlos's submission succeeds, THE SYSTEM SHALL send a confirmation text in Spanish with the receipt number and the PDF. (9.2)
17. **D17** THE repository SHALL include 2 sample paystub images and 1 sample earnings screenshot in `seed/sample_docs/`, synthetic, clearly fake, and without real brand logos. (9.2)
18. **D18** WHEN a member is the parent of a 10-year-old, THE SYSTEM SHALL reach `LIKELY_EXEMPT` without asking about hours. (9.3)
19. **D19** WHEN a member is enrolled half-time in school, THE SYSTEM SHALL reach `LIKELY_MEETS` by the school path. (9.3)
20. **D20** WHEN a member reports $300 income and 50 volunteer hours, THE SYSTEM SHALL reach `LIKELY_MEETS` by the combination path (300 / 7.25 = about 41, plus 50 = 91 >= 80) and flag it in the case notes. (9.3)
21. **D21** WHEN a member lost their job and has no hours, THE SYSTEM SHALL say honestly that they likely do not meet the rule, give the MassHealth number, and suggest the Health Connector. (9.3)
22. **D22** WHEN a member asks "Is this a scam?", THE SYSTEM SHALL follow the R33 safety script. (9.3)
23. **D23** WHEN a member offers an SSN, THE SYSTEM SHALL refuse it and redact it from the stored transcript. (9.3)
24. **D24** WHEN a conversation comes from an unknown phone number, THE SYSTEM SHALL verify by MassHealth ID plus date of birth. (9.3)
25. **D25** WHEN a member says they earned $900 and their screenshot shows $600, THE SYSTEM SHALL ask the member about the difference. (9.3)

### Requirement 9: Testing and Kiro evidence

**User Story:** As the hackathon team, I want automated tests that run without an API key and that cover the rules with property-based tests, so that changes stay safe and our Kiro usage is visible to judges.

#### Acceptance Criteria

1. **T1** THE rules engine unit tests SHALL cover every path and every exemption, including edge values $579.99, $580.00, 79 hours, 80 hours, and ages 18, 19, 64, and 65.
2. **T2** FOR ALL generated facts with `monthly_net_income >= 580` and no disqualifying age, THE rules engine SHALL return `LIKELY_MEETS` or `LIKELY_EXEMPT` (Hypothesis property).
3. **T3** FOR ALL generated facts where any exemption is true, THE rules engine SHALL return `LIKELY_EXEMPT` regardless of hours or income (Hypothesis property).
4. **T4** FOR ALL generated facts, increasing hours or income SHALL NOT turn a "meets" result into "does not meet" (Hypothesis monotonicity property).
5. **T5** FOR ALL generated facts where `income / 7.25 + volunteer + training + work hours >= 80`, THE rules engine SHALL return "meets" (Hypothesis combination property).
6. **T6** FOR ALL random text containing a 9-digit SSN-shaped string or a 13 to 19 digit card-shaped string, THE redactor SHALL remove it (Hypothesis property).
7. **T7** THE Twilio adapter tests SHALL cover signature validation, the immediate empty TwiML response, and the media download path.
8. **T8** THE Vapi adapter tests SHALL check the SSE format: valid chunks, a final `[DONE]`, and filler text arriving before tool results.
9. **T9** THE conversation tests SHALL use a fake LLM client that replays scripted tool calls, so that CI does not need an API key.
10. **T10** WHERE the `live` marker is selected (`-m live`), THE test suite SHALL run the two demo scenarios against the real Claude API.
11. **T11** THE SYSTEM SHALL log time to first token for each voice turn as an `Event`, and `scripts/latency_report.py` SHALL print p50 and p95.
12. **T12** THE repository SHALL commit the `.kiro/` directory (specs, steering, hooks) at the root and SHALL NOT gitignore it.

## Open items

- [DEFAULT] Combination path: income converted to hours (`income / 7.25`) may be combined with volunteer or training hours. Flag in case notes as "combination path, confirm with MassHealth guidance." (SPEC 3.2)
- [DEFAULT] Gig or self-employed member who does not know expenses: use gross earnings and add a note. (SPEC 3.2)
- [DEFAULT] Offer an attestation when documents are not reasonably available, and flag the case. (SPEC 3.5)
- [DEFAULT] Stack choices: Python 3.12, FastAPI, SQLModel on SQLite, twilio, pypdf and reportlab, uv, and the rest of SPEC 5.1.
- [DECIDED] The MVP supports only the AFVI "Attestation Form to Verify Income" (`assets/AFVI_2025-10.pdf`, fillable, 28 fields). It covers income-based paths. For exemption, school, and volunteer-only paths, the agent says MassHelp can't send the form yet and gives the MassHealth number. This replaces the JU-1 default in SPEC 5.8.
- [DEFAULT] Maria demo: hold submission until the screenshot arrives, or submit now with an attestation if she chooses. Confirm with the team. (SPEC 9.1 step 8, 13)
- [VERIFY] Coverage continues while a response is pending within the deadline. Check against MA guidance before stating it in the demo. (SPEC 3.4)
- [VERIFY] Twilio media URLs may require HTTP basic auth with the account SID and auth token. (SPEC 5.3)
- [VERIFY] Exact Vapi custom LLM request and response payload. Build an echo endpoint and log a real request before writing the adapter. (SPEC 5.3, 13)
- [VERIFY] Caller number at `call.customer.number` and call ID at `call.id` in the Vapi payload. (SPEC 5.3)
- [VERIFY] Vapi end-call phrase configuration (for example "Goodbye from MassHelp"). (SPEC 5.3)
- [VERIFY] A Vapi TTS voice that supports Spanish, and the transcriber's multilingual mode. (SPEC 5.3)
- [VERIFY] Twilio SMS registration (A2P 10DLC or toll-free verification) for texting the team's phones. Fallbacks: trial account to verified numbers, or show the SMS flow through `chat_cli.py`. (SPEC 13)
