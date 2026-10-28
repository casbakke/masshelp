# Kiro notes

Running log of how Kiro was used. The submission write-up is built from this.

## Spec
- Fed `SPEC.md` to Kiro to generate `.kiro/specs/masshelp/requirements.md` (EARS, R1-R37 kept, plus demo criteria D1-D25 and test criteria T1-T12), `design.md`, and `tasks.md`. Tasks trace to R-IDs.
- A Kiro sub-agent wrote the requirements and steering docs while the main agent built the backend in parallel.
- Changed course mid-build: the team chose AFVI as the only form. Kiro inspected the PDF (28 AcroForm fields), rendered previews to check placement, and recorded the decision in requirements and design.

## Steering
- `product.md`, `tech.md` (LLM hard rules: Haiku, streaming, no temperature, no prefill, caching), `structure.md`, `policy.md` (generated section), and `plain-language.md` (fileMatch on prompts and i18n).

## Hooks (`.kiro/hooks/`)
- Save rules YAML: regenerate `policy.md` and run rules tests.
- Save rules code: run unit and property tests.
- Save prompt, tools, runner, or i18n: run scripted conversation tests.
- Before an agent `git commit`: secret and SSN scan (blocks with exit 2).

## Property-based testing
- Hypothesis on the rules engine: income at or above $580 meets, any exemption is exempt, monotonic in hours and income, combination path meets.
- Hypothesis on redaction: SSN-shaped and card-shaped numbers are always removed.
- PBT caught a design question early: adding income hours and work hours double counts one job, so the combination path uses the larger of the two.

## What worked / didn't
- Worked: a scripted fake LLM let the full demo flows (identity, engine, documents, AFVI, consent, submit, SMS) run in CI with no API key.
- Snag: the installed SQLModel version requires timezone-aware datetimes; fixed in `util/dates.py`.
- Still to verify live: Vapi payload fields, Twilio texting to team phones, and real Claude behavior on the demo scripts.
