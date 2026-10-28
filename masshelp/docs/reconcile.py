"""Compare document amounts with what the member said (R22). Pure functions."""

from __future__ import annotations

import math
from datetime import date

# Average days per month, used to scale pay-period amounts to a month.
DAYS_PER_MONTH = 30.44
FREQUENCY_TO_MONTHLY = {"weekly": 4.33, "biweekly": 26 / 12, "semimonthly": 2.0, "monthly": 1.0}

INCOME_DOC_TYPES = ["pay_stub", "gig_earnings_summary", "employer_letter", "form_1099", "bank_statement"]
DOC_EMPLOYMENT_TYPE = {"pay_stub": "employee", "employer_letter": "employee", "gig_earnings_summary": "gig"}
DOC_TO_PROOF = {
    "pay_stub": "pay_stub",
    "gig_earnings_summary": "gig_earnings_screenshot",
    "bank_statement": "bank_statement",
    "employer_letter": "employer_letter",
    "form_1099": "form_1099",
    "school_enrollment": "school_enrollment_letter",
    "volunteer_log": "volunteer_letter",
    "training_letter": "training_letter",
    "medical_note": "doctor_note",
    "birth_certificate_or_child_school_record": "child_birth_certificate_or_school_record",
    "treatment_program_letter": "treatment_program_letter",
    "snap_tafdc_notice": "snap_tafdc_notice",
}


def proof_status(evaluation_proof_needed: list[dict], doc_types: list[str], attestation: bool) -> dict:
    """Which proof needs are covered by readable documents (or a signed statement)."""
    have = {DOC_TO_PROOF[t] for t in doc_types if t in DOC_TO_PROOF}
    covered, waiting = [], []
    for need in evaluation_proof_needed:
        if have & set(need["any_of"]):
            covered.append(need["covers"])
        else:
            waiting.append(need)
    complete = not waiting or attestation
    return {
        "complete": complete,
        "covered": covered,
        "waiting_for": [] if attestation else waiting,
        "attestation": attestation,
        "received_proof_types": sorted(have),
    }


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def monthly_estimate(extracted: dict) -> dict:
    """Scale one document's amounts to a monthly figure."""
    start, end = _date(extracted.get("period_start")), _date(extracted.get("period_end"))
    days = (end - start).days + 1 if start and end and end >= start else None
    factor: float | None
    if days is not None:
        factor = 1.0 if 28 <= days <= 31 else DAYS_PER_MONTH / days
    else:
        factor = FREQUENCY_TO_MONTHLY.get(extracted.get("pay_frequency") or "")
        if factor is None and extracted.get("doc_type") in ("gig_earnings_summary", "bank_statement"):
            factor = 1.0  # monthly summaries usually cover the month
    gross = extracted.get("gross_amount")
    hours = extracted.get("hours")
    return {
        "period_days": days,
        "monthly_factor": round(factor, 4) if factor is not None else None,
        "monthly_gross_estimate": round(gross * factor, 2) if gross is not None and factor is not None else None,
        "monthly_hours_estimate": math.floor(hours * factor + 1e-9) if hours is not None and factor is not None else None,
    }


def combined_estimate(docs: list[tuple[dict, dict]]) -> dict | None:
    """Combine (extracted, estimate) pairs of the best income document type present.

    Pay stubs and app summaries beat letters and bank statements. Several stubs are
    averaged (each is already scaled to a month).
    """
    readable = [(ex, est) for ex, est in docs if ex.get("readable") and ex.get("doc_type") in INCOME_DOC_TYPES]
    for doc_type in INCOME_DOC_TYPES:
        group = [(ex, est) for ex, est in readable if ex["doc_type"] == doc_type and est["monthly_gross_estimate"] is not None]
        if not group:
            continue
        gross = sum(est["monthly_gross_estimate"] for _, est in group) / len(group)
        hours_vals = [est["monthly_hours_estimate"] for _, est in group if est["monthly_hours_estimate"] is not None]
        employers = [ex["employer_or_platform"] for ex, _ in group if ex.get("employer_or_platform")]
        return {
            "doc_type": doc_type,
            "documents": len(group),
            "monthly_gross_estimate": round(gross, 2),
            "monthly_hours_estimate": math.floor(sum(hours_vals) / len(hours_vals)) if hours_vals else None,
            "employer_or_platform": employers[0] if employers else None,
            "employment_type": DOC_EMPLOYMENT_TYPE.get(doc_type),
        }
    return None


def compare_amounts(
    doc_gross: float, stated_gross: float | None, stated_net: float | None, tolerance: float
) -> dict:
    """Mismatch if the document differs from what the member said by more than `tolerance`.

    Stated gross: two-sided check. Only stated net (after work costs): the document's
    gross may be higher (costs explain it), so only flag when it's lower.
    """
    if stated_gross is not None:
        base = stated_gross
        diff = abs(doc_gross - base) / base if base > 0 else (1.0 if doc_gross > 0 else 0.0)
        return {
            "compared_to": "monthly_gross_income",
            "stated": stated_gross,
            "document": doc_gross,
            "difference_pct": round(diff * 100, 1),
            "mismatch": diff > tolerance + 1e-9,
        }
    if stated_net is not None:
        shortfall = (stated_net - doc_gross) / stated_net if stated_net > 0 else 0.0
        return {
            "compared_to": "monthly_net_income",
            "stated": stated_net,
            "document": doc_gross,
            "difference_pct": round(max(shortfall, 0.0) * 100, 1),
            "mismatch": shortfall > tolerance + 1e-9,
        }
    return {"compared_to": None, "stated": None, "document": doc_gross, "difference_pct": None, "mismatch": False}
