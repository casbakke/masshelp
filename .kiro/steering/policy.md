---
inclusion: always
---

# Policy

## Source

The rule comes from H.R. 1 (One Big Beautiful Bill Act, July 2025), the Medicaid community engagement requirement. It takes effect January 1, 2027 for ACA expansion adults aged 19 to 64 (MassHealth CarePlus). Massachusetts has not published final implementation details, so every policy detail may change.

## Hard constraints

- The deterministic rules engine (`masshelp/rules/engine.py`) decides outcomes. The LLM never states an outcome the engine did not return.
- All thresholds, exemptions, and proof types live in `masshelp/rules/masshealth_rules.yaml`; never hard-code them in prompts or code.
- Agent language always says likely.

## Current rules

<!-- BEGIN GENERATED POLICY -->
_Generated from masshelp/rules/masshealth_rules.yaml by scripts/gen_policy_docs.py. Do not edit by hand._

Rules version 2026-10-24-draft. Starts January 1, 2027 for CarePlus members aged 19 to 64. Massachusetts details are not final.

Ways to meet the rule for a month (any one):
- Hours: at least 80 hours in the month of work, volunteering, or job training, combined.
- School: enrolled at least half-time.
- Income: at least $580 in the month (80 x $7.25 minimum wage). Gig and self-employed: earnings after business costs like gas.
- Seasonal workers: average monthly income over the last 6 months of at least $580.
- Combination: income / $7.25 counts as hours, plus volunteer and training hours, at least 80.
- Weekly hours count as weekly x 4.33, rounded down.

Exemptions (screen these first; priority 1 always, priority 2 in one short combined question):
- `caretaker_child_13_or_younger` (priority 1): Parent or caretaker of a child 13 or younger
- `caretaker_disabled_person` (priority 1): Caretaker of a person with a disability
- `pregnant_or_postpartum` (priority 1): Pregnant or postpartum
- `medically_frail` (priority 1): Medically frail (blind, disabled, serious or complex medical condition, disabling mental disorder, or substance use disorder)
- `sud_treatment` (priority 1): In a substance use disorder treatment program
- `meets_snap_tafdc_work_rules` (priority 1): Already meeting SNAP or TAFDC work requirements
- `incarcerated_or_recently_released` (priority 2): Incarcerated, or released within the last 90 days
- `american_indian_alaska_native` (priority 2): American Indian or Alaska Native
- `veteran_total_disability` (priority 2): Veteran with a total disability rating
- `former_foster_youth_under_26` (priority 2): Former foster youth under 26
- `short_term_hardship` (priority 2): Short-term hardship (inpatient hospital stay, disaster area, or high-unemployment area) (state option, not decided)

Accepted proof (ids for request_document):
- `pay_stub`: Two recent pay stubs. Alternatives: employer_letter, bank_statement, attestation.
- `employer_letter`: Letter from your employer. Alternatives: pay_stub, bank_statement, attestation.
- `gig_earnings_screenshot`: Earnings summary screenshot from the app for the month. Alternatives: bank_statement, form_1099, self_employment_ledger, attestation.
- `bank_statement`: Bank statement showing deposits. Alternatives: attestation.
- `form_1099`: 1099 tax form. Alternatives: bank_statement, self_employment_ledger, attestation.
- `self_employment_ledger`: Self-employment log of income and expenses, with a signed statement. Alternatives: attestation.
- `volunteer_letter`: Letter or log from the organization with hours and a contact. Alternatives: attestation.
- `training_letter`: Enrollment or attendance letter from the job training program. Alternatives: attestation.
- `school_enrollment_letter`: Enrollment letter showing half-time or more. Alternatives: attestation.
- `child_birth_certificate_or_school_record`: Child's birth certificate or school record. Alternatives: attestation.
- `doctor_note`: Note from a doctor or provider. Alternatives: attestation.
- `treatment_program_letter`: Letter from the treatment program. Alternatives: attestation.
- `snap_tafdc_notice`: SNAP or TAFDC notice. Alternatives: attestation.
- `release_papers`: Release papers. Alternatives: attestation.
- `tribal_document`: Tribal enrollment or IHS document. Alternatives: attestation.
- `va_rating_letter`: VA disability rating letter. Alternatives: attestation.
- `foster_care_record`: Foster care record. Alternatives: attestation.
- `hospital_record`: Hospital discharge paper. Alternatives: attestation.
- `attestation`: Signed statement from the member (attestation).

Other changes to explain when relevant:
- Renewals move to every 6 months for this group.
- Coverage can reach back only 1 month instead of 3, so a gap can mean medical bills.

Contacts: MassHealth customer service 1-800-841-2900. Health Connector 1-877-623-6765 (mahealthconnector.org).
<!-- END GENERATED POLICY -->
