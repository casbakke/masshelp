"""Turn case state into AFVI content, a read-back summary, and PDF files (R26, R27, R30)."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session

from masshelp.answers import AnswerView, latest_answers
from masshelp.docs.ingest import case_documents
from masshelp.docs.reconcile import DOC_TO_PROOF, proof_status
from masshelp.forms.afvi import AfviContent, FinalStamp, money, render_afvi, us_date, us_phone
from masshelp.rules.models import Evaluation, RulesConfig, Status, YearMonth
from masshelp.store.models import Case, FormPdf, Member
from masshelp.util.dates import today, utcnow

# AFVI attests income, so it covers these paths only (MVP decision).
SUPPORTED_PATHS = {"income", "seasonal_income", "hours", "combination"}
PROOF_KEYS = {"Proof", "Still needed"}

TYPE_LABELS = {
    "employee": "Job income",
    "gig": "Self-employment income (app-based gig work)",
    "self_employed": "Self-employment income",
}


@dataclass
class BuiltForm:
    content: AfviContent
    read_back: dict[str, str]
    proof: dict
    facts_hash: str


def form_support(evaluation: Evaluation | None) -> tuple[bool, str | None]:
    if evaluation is None:
        return False, "Call evaluate_requirement first."
    if evaluation.status != Status.LIKELY_MEETS or evaluation.path not in SUPPORTED_PATHS:
        return False, (
            "MassHelp can only fill the income attestation form (AFVI) right now. "
            "For this path, tell the member MassHelp can't send this one for them yet, and give "
            "the MassHealth number so they can send their proof directly."
        )
    income = evaluation.derived.get("countable_income") or 0
    work_hours = evaluation.derived.get("monthly_work_hours") or 0
    if income <= 0 and work_hours <= 0:
        return False, "The income form needs income or work hours. Volunteer or training only is not supported yet."
    return True, None


def current_proof(session: Session, case: Case, evaluation: Evaluation, answers: dict[str, AnswerView]) -> dict:
    docs = [d for d in case_documents(session, case.id) if d.readable and not d.mismatch_flag and d.doc_type]
    attestation = bool(answers.get("attestation_accepted") and answers["attestation_accepted"].value is True)
    status = proof_status(evaluation.proof_needed, [d.doc_type for d in docs], attestation)
    status["documents"] = [{"id": d.id, "doc_type": d.doc_type} for d in docs]
    return status


def _v(answers: dict[str, AnswerView], field: str):
    view = answers.get(field)
    return view.value if view else None


def build_form(services, session: Session, case: Case, member: Member, evaluation: Evaluation) -> BuiltForm:
    rules: RulesConfig = services.rules
    answers = latest_answers(session, case.id)
    proof = current_proof(session, case, evaluation, answers)

    et = _v(answers, "employment_type")
    employer = _v(answers, "employer_or_platform")
    gross = _v(answers, "monthly_gross_income")
    expenses = _v(answers, "monthly_expenses")
    net = _v(answers, "monthly_net_income")
    weekly = _v(answers, "weekly_hours")
    work_hours = evaluation.derived.get("monthly_work_hours")
    volunteer = _v(answers, "volunteer_hours")
    training = _v(answers, "training_hours")
    countable = evaluation.derived.get("countable_income") or 0.0
    self_emp = et in ("gig", "self_employed")
    month = YearMonth.parse(case.verify_month) if case.verify_month else YearMonth.from_date(today())
    month_label = month.first_day.strftime("%B %Y")

    # Income detail (page 1): amount and how often.
    type_label = TYPE_LABELS.get(et or "", "Income")
    detail = [f"{type_label}{f' from {employer}' if employer else ''}:"]
    if gross is not None:
        detail.append(f"about {money(gross)} per month" + (" before work costs." if self_emp else " (gross wages)."))
    if self_emp and expenses is not None:
        detail.append(f"Work costs (gas, mileage) about {money(expenses)} per month.")
    if self_emp and net is not None:
        detail.append(f"About {money(net)} per month after work costs.")
    if not self_emp and gross is None and net is not None:
        detail.append(f"about {money(net)} per month.")
    detail.append("Received monthly." if not _v(answers, "is_seasonal") else "Seasonal income.")
    if weekly is not None:
        detail.append(f"About {weekly:g} hours a week.")
    elif work_hours:
        detail.append(f"About {work_hours:g} hours in {month_label}.")
    if volunteer:
        detail.append(f"Also {volunteer:g} volunteer hours in {month_label}" +
                      (f" at {_v(answers, 'volunteer_org')}." if _v(answers, "volunteer_org") else "."))
    if training:
        detail.append(f"Also {training:g} job training hours in {month_label}.")

    # Reason checkbox and explanation (page 2).
    has_docs = bool(proof["documents"])
    if self_emp:
        reason = "does_not_exist"
    elif not has_docs:
        reason = "cannot_access"
    else:
        reason = None
    doc_labels = sorted({rules.proof_types[DOC_TO_PROOF[d["doc_type"]]].label
                         for d in proof["documents"] if d["doc_type"] in DOC_TO_PROOF})
    explanation = [f"This is for the MassHealth work rule check for {month_label}."]
    if self_emp:
        explanation.append(
            f"I work for myself{f' through {employer}' if employer else ''}. "
            "I do not get pay stubs, so documents like pay stubs do not exist for this income."
        )
    if has_docs:
        explanation.append("I am including: " + "; ".join(doc_labels) + ".")
    elif proof["attestation"]:
        explanation.append("I do not have documents for this income right now, so I am signing this statement that it is true.")
    for note in evaluation.notes:
        explanation.append(f"Note: {note}")
    explanation.append("Prepared with MassHelp, an automated assistant. MassHealth makes the final decision.")

    expected = _v(answers, "expected_annual_income")
    expected = float(expected) if expected is not None else round(countable * 12, 2)
    income_types = ["self_employment_income" if self_emp else "job_income"] if (countable or work_hours) else []

    content = AfviContent(
        head_of_household_name=f"{member.first_name} {member.last_name}",
        member_id=member.masshealth_id,
        phone=us_phone(member.phone_e164 or case.phone_e164),
        todays_date=us_date(today()),
        expected_annual_income=f"{expected:,.2f}",
        reason=reason,
        income_types=income_types,
        income_detail=" ".join(detail),
        explanation="\n\n".join(explanation),
    )

    read_back: dict[str, str] = {
        "Name": content.head_of_household_name,
        "MassHealth ID": content.member_id,
        "Phone": content.phone,
        "Month": month_label,
        "Type of income": type_label,
    }
    if employer:
        read_back["Employer or app"] = str(employer)
    if gross is not None:
        read_back["Monthly income before costs" if self_emp else "Monthly income"] = money(gross)
    if self_emp and expenses is not None:
        read_back["Monthly work costs"] = money(expenses)
    if self_emp and net is not None:
        read_back["Monthly income after costs"] = money(net)
    if weekly is not None:
        read_back["Hours per week"] = f"{weekly:g}"
    if volunteer:
        read_back["Volunteer hours"] = f"{volunteer:g}"
    if training:
        read_back["Training hours"] = f"{training:g}"
    read_back["Expected income this year"] = money(expected)
    if reason:
        read_back["Reason for this form"] = (
            "Documents for this income do not exist" if reason == "does_not_exist"
            else "I can't get documents for this income right now"
        )
    read_back["Proof"] = "; ".join(doc_labels) if doc_labels else (
        "Signed statement" if proof["attestation"] else "None yet")
    waiting = [" or ".join(rules.proof_types[o].label for o in need["any_of"][:2]) for need in proof["waiting_for"]]
    if waiting:
        read_back["Still needed"] = "; ".join(waiting)

    hashed = {k: v for k, v in read_back.items() if k not in PROOF_KEYS}
    facts_hash = hashlib.sha256(json.dumps(hashed, sort_keys=True).encode()).hexdigest()[:16]
    return BuiltForm(content=content, read_back=read_back, proof=proof, facts_hash=facts_hash)


def write_pdf(services, session: Session, case: Case, built: BuiltForm, *, kind: str,
              stamp: FinalStamp | None = None) -> FormPdf:
    settings = services.settings
    pdf = FormPdf(
        case_id=case.id, kind=kind, path="", fields_json=json.dumps(built.read_back),
        facts_hash=built.facts_hash, expires_at=utcnow() + timedelta(days=settings.file_link_days),
    )
    target = settings.pdf_dir / case.id / f"{pdf.id}.pdf"
    if settings.demo_fixed_pdf:
        # R30: deterministic demo output.
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(settings.demo_fixed_pdf, target)
    else:
        render_afvi(built.content, target, stamp=stamp)
    pdf.path = str(target)
    session.add(pdf)
    session.commit()
    return pdf


def file_url(services, pdf: FormPdf) -> str:
    return f"{services.settings.public_base_url.rstrip('/')}/files/{pdf.token}"
