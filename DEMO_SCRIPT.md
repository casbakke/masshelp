# MassHelp 2-Minute Live Demo Script

A phone call between **Maria** (played by a team member on their own phone) and the **MassHelp agent**. Hard limit: 2:00. The script is budgeted at about 1:50 to leave room for latency.

When `DEMO_MODE=true`, the agent loads this file (see `SPEC.md` section 5.4) and says its lines as written, as long as Maria's replies match the script closely.

---

## Before you start (not timed)

- [ ] Run `uv run scripts/reset_demo.py`. This clears Maria's case and reseeds her as "open, work requirement verification, due 2026-12-31".
- [ ] `.env` has `DEMO_MODE=true`, `DEMO_TODAY=2026-12-01`, and `DEMO_PHONE_MARIA=<presenter's phone number>`.
- [ ] Server running, ngrok up, Vapi assistant pointed at the current ngrok URL. Make one test call and hang up.
- [ ] The sample earnings screenshot (`seed/sample_docs/earnings_november.png`, net $904.12 for November 2026) is the **most recent photo** in the presenter's camera roll.
- [ ] Presenter's phone is on speaker, loud, and the screen is visible to the camera or audience, with Messages ready to open.
- [ ] Do Not Disturb is off for SMS from the MassHelp number.

---

## The script

Times are cumulative targets. "Tools" lists what the agent calls during that line; they are not spoken.

| Time | Speaker | Line | Tools |
| --- | --- | --- | --- |
| 0:00 | *(Presenter dials MassHelp on speaker)* | | |
| 0:05 | **AGENT** | Hi, this is MassHelp, a free automated helper for MassHealth members. I'm not MassHealth. To get started, what's your date of birth? | *(first message, no tools)* |
| 0:13 | **MARIA** | June fourth, 1992. | |
| 0:16 | **AGENT** | Thanks, Maria. Because of a new rule, MassHealth needs proof of your work or income by December 31st, and we can do it right now. First: do you care for a child 13 or under, are you pregnant, or do you have a health condition that limits your work? | `verify_identity`, `get_case_status` |
| 0:31 | **MARIA** | No, none of those. | `record_answers` |
| 0:34 | **AGENT** | Okay. What kind of work do you do, and about how much do you make in a month? | |
| 0:39 | **MARIA** | I drive for a delivery app, about 25 hours a week. I make around 900 dollars a month after gas. | |
| 0:46 | **AGENT** | One second. ... Good news: that's more than the 580 dollars the rule asks for, so you likely qualify. Do you have pay stubs? | `record_answers`, `evaluate_requirement` |
| 0:55 | **MARIA** | No, the app doesn't give pay stubs. | |
| 0:58 | **AGENT** | That's fine. A screenshot of your November earnings from the app works instead. I just texted you. Send it there. | `request_document` (SMS goes out) |
| 1:05 | *(Presenter opens Messages, shows the text, attaches the screenshot, sends it)* | | |
| 1:17 | **MARIA** | Okay, sent. | |
| 1:19 | **AGENT** | Got it. It shows 904 dollars for November, which matches. Here's what I'll send: Maria Santos, self-employed delivery driver, about 25 hours a week, 900 dollars a month after costs, for November 2026. Is that right, and may I submit it to MassHealth for you? | `get_documents`, `prepare_form` |
| 1:36 | **MARIA** | Yes, go ahead. | |
| 1:38 | **AGENT** | One moment. ... Done. I've texted you your receipt and a copy of the form. MassHealth makes the final decision and will reach out if they need anything else. Goodbye from MassHelp. | `record_consent`, `submit_to_masshealth`, `send_confirmation_sms` |
| 1:50 | *(Call ends. Presenter shows the confirmation text: receipt number and PDF link. Tap the link to show the filled, watermarked form.)* | | |
| 2:00 | **END** | | |

Spoken words: about 210. At a normal pace plus about 1 second of response time per agent turn, this fits in 1:50.

---

## What the audience sees

1. **0:00 to 1:05:** a normal phone call. The agent screens exemptions first, never asks about hours once income qualifies, and never asks for an SSN.
2. **1:05:** the case jumps from voice to SMS. A text from MassHelp asking for the screenshot arrives during the call.
3. **1:19:** the agent read the screenshot and checked it against what Maria said.
4. **1:50:** the confirmation text with a receipt and the filled PDF.

---

## Agent rules in demo mode

These go into the system prompt when `DEMO_MODE=true`, after the normal instructions:

1. Say each AGENT line above **word for word**, in order, when Maria's reply means the same thing as the scripted MARIA line. Numbers are spoken as words ("nine hundred dollars") by the TTS.
2. Still call the listed tools on each line. Don't state anything the tools didn't return. If `evaluate_requirement` or `get_documents` returns something different from the script (for example, a different amount), say what the tool returned in the same style and length.
3. If Maria says something off-script, answer it in one short sentence using normal rules, then return to the next scripted line.
4. Don't add greetings, small talk, recaps, or extra questions. Keep each turn as short as the scripted one.
5. Combine read-back and consent into one turn (line 1:19), as written. Outside demo mode they can be separate turns.
6. If the screenshot hasn't been processed when Maria says "sent", `get_documents` waits up to 8 seconds. If it's still not there, say: "It's still coming through. One more second." and call `get_documents` once more.

---

## If something goes wrong (live fallback)

| Problem | What the presenter does |
| --- | --- |
| Agent mishears the date of birth | Repeat it once, clearly: "June fourth, nineteen ninety-two." |
| Screenshot text doesn't arrive within 5 seconds | Keep talking: "While that comes through, the agent has already logged my answers." Then say "Okay, sent." again. |
| Agent goes off-script or is slow | Don't fight it. Give the next scripted MARIA line. The agent will catch up to the script. |
| Call drops | Show the pre-recorded backup video of the same script (record one the day before). |

---

## Spanish SMS variant (if you have 30 extra seconds)

After the call, text the MassHelp number from a second phone seeded as Carlos: "Hola, recibí una carta de MassHealth." Show the Spanish reply asking for date of birth, then stop. It shows multilingual support without spending a full scenario.
