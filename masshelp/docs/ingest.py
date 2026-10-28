"""Store incoming media, extract fields, reconcile with stated answers, and record
document-sourced answers when nothing conflicts (R21, R22, R23).
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
from dataclasses import dataclass

from sqlmodel import Session, select

from masshelp.answers import latest_answers, save_answer
from masshelp.cases import identity_valid
from masshelp.docs.extract import extract_document
from masshelp.docs.reconcile import combined_estimate, compare_amounts, monthly_estimate
from masshelp.store.db import log_event
from masshelp.store.models import Case, Document
from masshelp.util.dates import utcnow

EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp", "application/pdf": ".pdf"}


@dataclass
class IncomingMedia:
    data: bytes
    content_type: str
    source_url: str | None = None


async def ingest_media(services, case_id: str, media: list[IncomingMedia]) -> str:
    """Process media for a case. Returns a short note for the agent's user message."""
    if not media:
        return ""
    settings = services.settings
    folder = settings.media_dir / case_id
    folder.mkdir(parents=True, exist_ok=True)

    extractions = await asyncio.gather(
        *(extract_document(services.llm, m.data, m.content_type) for m in media)
    )

    with services.db.session() as s:
        case = s.get(Case, case_id)
        docs: list[Document] = []
        for m, extracted in zip(media, extractions, strict=True):
            ctype = (m.content_type or "").split(";")[0].strip().lower()
            doc = Document(case_id=case_id, media_path="", content_type=ctype)
            ext = EXT_BY_TYPE.get(ctype) or mimetypes.guess_extension(ctype) or ".bin"
            path = folder / f"{doc.id}{ext}"
            path.write_bytes(m.data)
            doc.media_path = str(path)
            doc.readable = bool(extracted.get("readable"))
            doc.doc_type = extracted.get("doc_type") if doc.readable else None
            doc.extracted_json = json.dumps(extracted)
            doc.derived_json = json.dumps(monthly_estimate(extracted))
            s.add(doc)
            docs.append(doc)
        s.commit()
        log_event(s, case_id, "documents_received", {"count": len(docs), "types": [d.doc_type for d in docs]})

        summary = refresh_reconciliation(services, s, case)
        if case is not None and identity_valid(case, settings) and not summary["mismatch"]:
            recorded = record_document_answers(s, case, summary)
            summary["answers_recorded_from_documents"] = recorded
        s.commit()

    return document_note(docs, summary)


def case_documents(session: Session, case_id: str) -> list[Document]:
    return list(session.exec(select(Document).where(Document.case_id == case_id).order_by(Document.created_at)))


def refresh_reconciliation(services, session: Session, case: Case | None) -> dict:
    """Recompute the combined estimate and mismatch flags against current answers."""
    if case is None:
        return {"estimate": None, "comparison": None, "mismatch": False}
    docs = case_documents(session, case.id)
    pairs = [(json.loads(d.extracted_json), json.loads(d.derived_json)) for d in docs]
    estimate = combined_estimate(pairs)
    comparison = None
    if estimate is not None:
        answers = latest_answers(session, case.id)
        stated_gross = _stated(answers, "monthly_gross_income")
        stated_net = _stated(answers, "monthly_net_income")
        comparison = compare_amounts(
            estimate["monthly_gross_estimate"], stated_gross, stated_net, services.rules.mismatch_tolerance
        )
        for d in docs:
            if d.doc_type == estimate["doc_type"]:
                d.mismatch_flag = comparison["mismatch"]
                d.mismatch_json = json.dumps(comparison)
                session.add(d)
    return {"estimate": estimate, "comparison": comparison, "mismatch": bool(comparison and comparison["mismatch"])}


def _stated(answers, field: str) -> float | None:
    view = answers.get(field)
    # Only compare against what the member said, not values we took from documents.
    if view is None or view.source == "document":
        return None
    return float(view.value)


def record_document_answers(session: Session, case: Case, summary: dict) -> list[str]:
    """Fill in facts the member hasn't stated, from documents (source=document)."""
    estimate = summary.get("estimate")
    if not estimate:
        return []
    answers = latest_answers(session, case.id)
    recorded: list[str] = []

    def put(field: str, value: object) -> None:
        if value is None:
            return
        existing = answers.get(field)
        if existing is not None and existing.source != "document":
            return  # never overwrite what the member said
        if existing is not None and existing.value == value:
            return
        save_answer(session, case.id, field, value, "document")
        recorded.append(field)

    put("monthly_gross_income", estimate["monthly_gross_estimate"])
    put("employer_or_platform", estimate["employer_or_platform"])
    put("employment_type", estimate["employment_type"])
    if "weekly_hours" not in answers or answers["weekly_hours"].source == "document":
        put("monthly_hours", estimate["monthly_hours_estimate"])
    case.updated_at = utcnow()
    session.add(case)
    return recorded


def document_note(docs: list[Document], summary: dict) -> str:
    lines = [f"[Member sent {len(docs)} file(s) by text.]"]
    for i, d in enumerate(docs, 1):
        ex = json.loads(d.extracted_json)
        if not d.readable:
            lines.append(f"File {i}: could not be read (reason: {ex.get('unreadable_reason') or 'unknown'}).")
            continue
        bits = [ex.get("doc_type") or "document"]
        if ex.get("employer_or_platform"):
            bits.append(f"from {ex['employer_or_platform']}")
        if ex.get("period_start") or ex.get("period_end"):
            bits.append(f"period {ex.get('period_start')} to {ex.get('period_end')}")
        if ex.get("gross_amount") is not None:
            bits.append(f"gross ${ex['gross_amount']:,.2f}")
        if ex.get("hours") is not None:
            bits.append(f"{ex['hours']:g} hours")
        lines.append(f"File {i} ({d.id}): " + ", ".join(bits) + ".")
    est = summary.get("estimate")
    if est:
        hours = est["monthly_hours_estimate"]
        lines.append(
            f"Monthly estimate from documents: ${est['monthly_gross_estimate']:,.2f}"
            + (f", {hours} hours" if hours is not None else "")
            + "."
        )
    cmp_ = summary.get("comparison")
    if cmp_ and cmp_.get("compared_to"):
        if cmp_["mismatch"]:
            lines.append(
                f"MISMATCH: member said ${cmp_['stated']:,.2f} ({cmp_['compared_to']}), documents show "
                f"${cmp_['document']:,.2f} ({cmp_['difference_pct']}% off). Ask the member about it."
            )
        else:
            lines.append(f"Matches what the member said (within {cmp_['difference_pct']}%).")
    if summary.get("answers_recorded_from_documents"):
        lines.append("Recorded from documents: " + ", ".join(summary["answers_recorded_from_documents"]) + ".")
    return "\n".join(lines)
