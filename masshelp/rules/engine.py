"""Deterministic rules engine for the MassHealth work rule (G4, R19).

Pure: no I/O, no LLM, no clock. Takes facts, a month, and the rules config, and
returns an Evaluation. The agent may only state outcomes this function returns.

Order (SPEC 5.6): age and group, exemptions, income, school, hours, combination.
"""

from __future__ import annotations

import math

from masshelp.rules.models import (
    EmploymentType,
    Evaluation,
    MemberFacts,
    RulesConfig,
    SchoolEnrollment,
    Status,
    YearMonth,
)

# Float tolerance so 580.00 and 80.00 always count as meeting the threshold.
EPS = 1e-9

PATH_ORDER = ["income", "seasonal_income", "school", "hours", "combination"]

_SELF_EMPLOYED = {EmploymentType.GIG, EmploymentType.SELF_EMPLOYED}


def evaluate(facts: MemberFacts, month: YearMonth, rules: RulesConfig) -> Evaluation:
    # 1. Group and age. People outside the group are not subject to the rule.
    if facts.program is not None and facts.program != rules.program:
        return Evaluation(
            status=Status.LIKELY_EXEMPT,
            path="not_in_expansion_group",
            reasons=[f"Coverage type {facts.program} is not {rules.program}, so the work rule likely does not apply."],
        )
    if facts.age is not None and not (rules.age_min <= facts.age <= rules.age_max):
        return Evaluation(
            status=Status.LIKELY_EXEMPT,
            path="age_outside_range",
            reasons=[
                f"Age {facts.age} is outside {rules.age_min} to {rules.age_max} for {month}, "
                "so the work rule likely does not apply."
            ],
        )

    notes: list[str] = []
    if facts.age is None:
        notes.append("Age unknown; assumed to be in the covered range.")

    # 2. Exemptions. Any known exemption wins, regardless of hours or income.
    exemption = rules.exemption(facts.exemption_type)
    if exemption is not None:
        if exemption.state_option:
            notes.append(rules.notes["state_option_undecided"])
        return Evaluation(
            status=Status.LIKELY_EXEMPT,
            path=f"exemption:{exemption.id}",
            reasons=[f"Likely exempt: {exemption.label}."],
            proof_needed=[_need(f"exemption:{exemption.id}", exemption.proof)],
            notes=notes,
        )
    exemption_pending = facts.is_exempt_claimed is True

    # 3-6. Paths. Each is computed independently, then ordered.
    countable, income_notes = countable_income(facts)
    notes.extend(income_notes)
    work_hours = monthly_work_hours(facts, rules)
    volunteer = facts.volunteer_hours or 0.0
    training = facts.training_hours or 0.0
    activity_hours = (work_hours or 0.0) + volunteer + training
    income_hours = (countable or 0.0) / rules.federal_minimum_wage
    # Income stands in for the work hours that earned it, so take the larger of the two
    # rather than adding both (adding would count the same job twice).
    combination_hours = max(work_hours or 0.0, income_hours) + volunteer + training

    met: list[str] = []
    reasons: list[str] = []
    threshold = rules.income_threshold
    hours_needed = rules.hours_threshold

    if countable is not None and countable + EPS >= threshold:
        met.append("income")
        reasons.append(f"Monthly countable income ${countable:,.2f} is at least ${threshold:,.2f}.")
    if (
        facts.is_seasonal
        and facts.seasonal_average_monthly_income is not None
        and facts.seasonal_average_monthly_income + EPS >= threshold
    ):
        met.append("seasonal_income")
        reasons.append(
            f"Seasonal worker: average monthly income over the last {rules.seasonal_lookback_months} months "
            f"${facts.seasonal_average_monthly_income:,.2f} is at least ${threshold:,.2f}."
        )
    if facts.school_enrollment in (SchoolEnrollment.FULL_TIME, SchoolEnrollment.HALF_TIME):
        met.append("school")
        reasons.append("Enrolled in school at least half-time.")
    if activity_hours + EPS >= hours_needed:
        met.append("hours")
        reasons.append(
            f"Work, volunteer, and training hours add up to {activity_hours:g} for the month "
            f"(at least {hours_needed:g})."
        )
    if "income" not in met and "hours" not in met and combination_hours + EPS >= hours_needed:
        met.append("combination")
        reasons.append(
            f"Income counted as {income_hours:.1f} hours (${countable or 0:,.2f} / ${rules.federal_minimum_wage}) "
            f"plus volunteer and training hours is {combination_hours:.1f} hours (at least {hours_needed:g})."
        )
        notes.append(rules.notes["combination_path"])

    derived = {
        "countable_income": round(countable, 2) if countable is not None else None,
        "monthly_work_hours": work_hours,
        "activity_hours": round(activity_hours, 2),
        "income_hours": round(income_hours, 2),
        "combination_hours": round(combination_hours, 2),
    }

    if met:
        met.sort(key=PATH_ORDER.index)
        path = met[0]
        return Evaluation(
            status=Status.LIKELY_MEETS,
            path=path,
            other_paths_met=met[1:],
            reasons=reasons,
            proof_needed=proof_for_path(path, facts, rules),
            notes=notes,
            derived=derived,
        )

    # Nothing met. Only say "does not meet" once every path has been checked (R20).
    missing: list[str] = []
    no_job = facts.employment_type == EmploymentType.NONE
    if exemption_pending:
        missing.append("exemption_type")
    elif facts.is_exempt_claimed is None:
        missing.append("is_exempt_claimed")
    if countable is None:
        if facts.employment_type is None:
            missing.append("employment_type")
        missing.append("monthly_gross_income")
    if work_hours is None and not no_job:
        missing.append("weekly_hours")
    if facts.is_seasonal and facts.seasonal_average_monthly_income is None:
        missing.append("seasonal_average_monthly_income")
    if facts.school_enrollment is None:
        missing.append("school_enrollment")
    if facts.volunteer_hours is None:
        missing.append("volunteer_hours")
    if facts.training_hours is None:
        missing.append("training_hours")

    if missing:
        return Evaluation(
            status=Status.NEEDS_MORE_INFO,
            reasons=["Not enough information yet to check every way to meet the rule."],
            missing=missing,
            notes=notes,
            derived=derived,
        )

    return Evaluation(
        status=Status.LIKELY_DOES_NOT_MEET,
        reasons=[
            f"Monthly countable income ${countable or 0:,.2f} is below ${threshold:,.2f}.",
            f"Work, volunteer, and training hours total {activity_hours:g}, below {hours_needed:g}.",
            "Not enrolled in school at least half-time.",
            f"Combined (income as hours plus volunteer and training) is {combination_hours:.1f} hours, below {hours_needed:g}.",
        ],
        notes=notes,
        derived=derived,
    )


def countable_income(facts: MemberFacts) -> tuple[float | None, list[str]]:
    """Monthly income that counts toward the $580 test.

    Employees: gross wages (take-home pay is never lower than gross, so max() is safe
    if both were recorded). Self-employed and gig: net of business expenses; if
    expenses are unknown, gross with a note [DEFAULT].
    """
    gross = _nonneg(facts.monthly_gross_income)
    net = _nonneg(facts.monthly_net_income)
    expenses = _nonneg(facts.monthly_expenses)
    et = facts.employment_type
    notes: list[str] = []

    if et == EmploymentType.EMPLOYEE:
        values = [v for v in (gross, net) if v is not None]
        return (max(values) if values else None), notes

    if et in _SELF_EMPLOYED:
        if net is not None:
            return net, notes
        if gross is not None and expenses is not None:
            return max(gross - expenses, 0.0), notes
        if gross is not None:
            notes.append("Self-employed or gig member did not know business expenses, so gross earnings were used.")
            return gross, notes
        return None, notes

    # Unknown or no employment type.
    if net is not None:
        return net, notes
    if gross is not None:
        return (max(gross - expenses, 0.0) if expenses is not None else gross), notes
    if et == EmploymentType.NONE:
        return 0.0, notes
    return None, notes


def monthly_work_hours(facts: MemberFacts, rules: RulesConfig) -> float | None:
    """Monthly work hours. Weekly hours convert as weekly x 4.33, rounded down."""
    if facts.monthly_hours is not None:
        return max(facts.monthly_hours, 0.0)
    if facts.weekly_hours is not None:
        return float(math.floor(max(facts.weekly_hours, 0.0) * rules.weeks_per_month + EPS))
    if facts.employment_type == EmploymentType.NONE:
        return 0.0
    return None


def proof_for_path(path: str, facts: MemberFacts, rules: RulesConfig) -> list[dict]:
    """Proof options for a met path. Each entry is satisfied by any one of its options."""
    self_employed = facts.employment_type in _SELF_EMPLOYED
    pp = rules.path_proof
    income_key = "income_self_employed" if self_employed else "income_employee"
    needs: list[dict] = []
    if path == "income":
        needs.append(_need("income", pp[income_key]))
    elif path == "seasonal_income":
        needs.append(_need("seasonal_income", pp["seasonal_income"]))
    elif path == "school":
        needs.append(_need("school", pp["school"]))
    elif path in ("hours", "combination"):
        if path == "combination" and (facts.monthly_gross_income or facts.monthly_net_income):
            needs.append(_need("income", pp[income_key]))
        elif monthly_work_hours(facts, rules):
            key = "work_hours_self_employed" if self_employed else "work_hours_employee"
            needs.append(_need("work_hours", pp[key]))
        if facts.volunteer_hours:
            needs.append(_need("volunteer_hours", pp["volunteer_hours"]))
        if facts.training_hours:
            needs.append(_need("training_hours", pp["training_hours"]))
    return needs


def _need(covers: str, options: list[str]) -> dict:
    return {"covers": covers, "any_of": list(options)}


def _nonneg(value: float | None) -> float | None:
    if value is None:
        return None
    return max(float(value), 0.0)
