"""Vision extraction of document fields (R21). One non-streaming call per document,
with a JSON schema so the result is structured.
"""

from __future__ import annotations

import io
import logging

from masshelp.agent.llm import LLMClient, LLMError, image_block, pdf_block
from masshelp.util.redact import redact_obj

log = logging.getLogger(__name__)

DOC_TYPES = [
    "pay_stub",
    "gig_earnings_summary",
    "bank_statement",
    "employer_letter",
    "form_1099",
    "school_enrollment",
    "volunteer_log",
    "training_letter",
    "medical_note",
    "birth_certificate_or_child_school_record",
    "treatment_program_letter",
    "snap_tafdc_notice",
    "masshealth_notice",
    "other",
]

UNREADABLE_REASONS = ["blurry", "too_dark", "glare", "cut_off", "not_a_document", "other"]

_NS = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NN = {"anyOf": [{"type": "number"}, {"type": "null"}]}

EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "unreadable_reason": {"anyOf": [{"type": "string", "enum": UNREADABLE_REASONS}, {"type": "null"}]},
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "person_name": _NS,
        "employer_or_platform": _NS,
        "period_start": _NS,
        "period_end": _NS,
        "pay_frequency": {
            "anyOf": [
                {"type": "string", "enum": ["weekly", "biweekly", "semimonthly", "monthly", "other"]},
                {"type": "null"},
            ]
        },
        "gross_amount": _NN,
        "net_amount": _NN,
        "hours": _NN,
        "notes": _NS,
    },
    "required": [
        "readable",
        "unreadable_reason",
        "doc_type",
        "person_name",
        "employer_or_platform",
        "period_start",
        "period_end",
        "pay_frequency",
        "gross_amount",
        "net_amount",
        "hours",
        "notes",
    ],
    "additionalProperties": False,
}

EXTRACTION_PROMPT = """Extract fields from this document for a MassHealth work rule check.
Use null for anything not clearly visible. Do not guess.
- Dates as YYYY-MM-DD. Amounts in US dollars as plain numbers.
- Pay stub: gross_amount = gross pay for THIS pay period (not year-to-date). net_amount = net pay for this period. hours = hours worked this period.
- Gig or delivery app earnings screen: gross_amount = total earnings for the period shown. net_amount = null unless business expenses are shown. hours = active or online hours if shown.
- MassHealth letter: doc_type masshealth_notice; put the deadline and what is asked in notes.
- Never copy a Social Security number, bank account number, or card number into any field.
- Set readable=false and give unreadable_reason if you cannot read the key dates and amounts."""

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 3_500_000
MAX_IMAGE_DIM = 1600


def prepare_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Fix orientation and shrink big or unsupported images to JPEG for the API."""
    if content_type in SUPPORTED_IMAGE_TYPES and len(data) <= MAX_IMAGE_BYTES:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as img:
                if max(img.size) <= 2 * MAX_IMAGE_DIM:
                    return data, content_type
        except Exception:  # noqa: BLE001 - fall through to conversion
            pass
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"


def unreadable(reason: str, note: str | None = None) -> dict:
    return {
        "readable": False,
        "unreadable_reason": reason,
        "doc_type": "other",
        "person_name": None,
        "employer_or_platform": None,
        "period_start": None,
        "period_end": None,
        "pay_frequency": None,
        "gross_amount": None,
        "net_amount": None,
        "hours": None,
        "notes": note,
    }


async def extract_document(llm: LLMClient, data: bytes, content_type: str) -> dict:
    """Return the structured extraction. Never raises; problems become readable=false."""
    content_type = (content_type or "").split(";")[0].strip().lower()
    try:
        if content_type == "application/pdf":
            block = pdf_block(data)
        elif content_type.startswith("image/"):
            img, media_type = prepare_image(data, content_type)
            block = image_block(img, media_type)
        else:
            return unreadable("not_a_document", f"unsupported file type {content_type}")
    except Exception:  # noqa: BLE001 - corrupt or unsupported image
        log.exception("could not prepare image")
        return unreadable("other", "could not open the file")

    try:
        result = await llm.extract(
            content=[block, {"type": "text", "text": EXTRACTION_PROMPT}], schema=EXTRACTION_SCHEMA
        )
    except LLMError:
        log.exception("extraction call failed")
        return unreadable("other", "extraction failed")
    if not result:
        return unreadable("other", "no result")
    # Belt and braces: never store sensitive numbers even if the model copied one.
    return redact_obj(result)
