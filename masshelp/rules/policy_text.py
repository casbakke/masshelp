"""Render the rules config as markdown, for the system prompt and .kiro/steering/policy.md.

One source of truth: the prompt and the engine read the same YAML, so they never disagree.
"""

from __future__ import annotations

from masshelp.rules.models import RulesConfig


def policy_markdown(rules: RulesConfig) -> str:
    c = rules.contacts
    lines = [
        f"Rules version {rules.version}. Starts {rules.effective_date:%B %-d, %Y} for {rules.program} members "
        f"aged {rules.age_min} to {rules.age_max}. Massachusetts details are not final.",
        "",
        "Ways to meet the rule for a month (any one):",
        f"- Hours: at least {rules.hours_threshold:g} hours in the month of work, volunteering, or job training, combined.",
        "- School: enrolled at least half-time.",
        f"- Income: at least ${rules.income_threshold:,.0f} in the month "
        f"({rules.hours_threshold:g} x ${rules.federal_minimum_wage} minimum wage). Gig and self-employed: earnings after business costs like gas.",
        f"- Seasonal workers: average monthly income over the last {rules.seasonal_lookback_months} months of at least ${rules.income_threshold:,.0f}.",
        f"- Combination: income / ${rules.federal_minimum_wage} counts as hours, plus volunteer and training hours, at least {rules.hours_threshold:g}.",
        f"- Weekly hours count as weekly x {rules.weeks_per_month}, rounded down.",
        "",
        "Exemptions (screen these first; priority 1 always, priority 2 in one short combined question):",
    ]
    for ex in rules.exemptions:
        flag = " (state option, not decided)" if ex.state_option else ""
        lines.append(f"- `{ex.id}` (priority {ex.priority}): {ex.label}{flag}")
    lines += [
        "",
        "Accepted proof (ids for request_document):",
    ]
    for pid, pt in rules.proof_types.items():
        alts = f" Alternatives: {', '.join(pt.alternatives)}." if pt.alternatives else ""
        lines.append(f"- `{pid}`: {pt.label}.{alts}")
    lines += [
        "",
        "Other changes to explain when relevant:",
        f"- Renewals move to every {rules.renewal_months} months for this group.",
        f"- Coverage can reach back only {rules.retro_coverage_months_after} month instead of "
        f"{rules.retro_coverage_months_before}, so a gap can mean medical bills.",
        "",
        f"Contacts: MassHealth customer service {c['masshealth_customer_service']}. "
        f"Health Connector {c['health_connector']} ({c['health_connector_url']}).",
    ]
    return "\n".join(lines)
