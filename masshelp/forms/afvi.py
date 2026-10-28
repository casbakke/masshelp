"""Fill the AFVI "Attestation Form to Verify Income" (assets/AFVI_2025-10.pdf).

MVP decision: AFVI is the only supported form. It reports income, so it covers the
income, seasonal income, hours-from-work, and combination paths. Exemption, school,
and volunteer-only paths have no income to attest, so the form tool reports
"not supported" for them and the agent points the member to MassHealth.

Rendering: values are drawn with reportlab at each field's rectangle (looked up by
field name), then all widgets are removed. This renders the same in every viewer,
including phone browsers opening the SMS link. Every page gets the
"SAMPLE - NOT FOR SUBMISSION" watermark (R31). The form is always English (R12).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph

from masshelp.config import ROOT

WATERMARK = "SAMPLE - NOT FOR SUBMISSION"
HEADER_NOTE = "Filled by MassHelp, a free automated assistant (not MassHealth). Hackathon demo with dummy data."


@dataclass
class AfviContent:
    """Everything that goes on the form. Text is English."""

    head_of_household_name: str
    member_id: str
    phone: str
    todays_date: str
    expected_annual_income: str  # number formatted without "$" (the form prints it)
    reason: str | None  # cannot_access, does_not_exist, or None
    income_types: list[str]  # checkbox keys from the mapping
    income_detail: str
    explanation: str
    other_household_members: str = ""
    other_income_source: str = ""


@dataclass
class FinalStamp:
    """Added after consent and submission."""

    signer_name: str
    channel: str  # voice or sms
    consent_id: str
    consented_at: str  # "MM/DD/YYYY HH:MM UTC"
    signature_date: str  # MM/DD/YYYY
    receipt_number: str | None = None


@dataclass
class Mapping:
    form_id: str
    title: str
    template: Path
    text_fields: dict[str, str]
    multiline_fields: dict[str, str]
    checkboxes: dict[str, str]
    signature_line: dict[str, float] = field(default_factory=dict)


@lru_cache
def load_mapping(path: str) -> Mapping:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Mapping(
        form_id=raw["form_id"],
        title=raw["title"],
        template=ROOT / raw["template"],
        text_fields=raw["text_fields"],
        multiline_fields=raw["multiline_fields"],
        checkboxes=raw["checkboxes"],
        signature_line=raw.get("signature_line", {}),
    )


def default_mapping() -> Mapping:
    return load_mapping(str(Path(__file__).with_name("afvi_mapping.yaml")))


@lru_cache
def field_rects(template: str) -> dict[str, tuple[int, tuple[float, float, float, float]]]:
    """Field name -> (page index, rect) for every widget in the template."""
    reader = PdfReader(template)
    rects: dict[str, tuple[int, tuple[float, float, float, float]]] = {}
    for page_index, page in enumerate(reader.pages):
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            name = obj.get("/T")
            if name is None and obj.get("/Parent") is not None:
                name = obj["/Parent"].get_object().get("/T")
            if name is None:
                continue
            x0, y0, x1, y1 = (float(v) for v in obj["/Rect"])
            rects[str(name)] = (page_index, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return rects


def check_template(mapping: Mapping) -> list[str]:
    """Return mapped field names missing from the template (empty list = OK)."""
    rects = field_rects(str(mapping.template))
    names = [*mapping.text_fields.values(), *mapping.multiline_fields.values(), *mapping.checkboxes.values()]
    return [n for n in names if n not in rects]


# ---------------------------------------------------------------- rendering


def render_afvi(content: AfviContent, out_path: Path, *, stamp: FinalStamp | None = None,
                mapping: Mapping | None = None) -> Path:
    mapping = mapping or default_mapping()
    template = str(mapping.template)
    rects = field_rects(template)
    reader = PdfReader(template)
    n_pages = len(reader.pages)
    sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages]

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=sizes[0])
    draws: dict[int, list] = {i: [] for i in range(n_pages)}

    def text(key: str, value: str) -> None:
        if value:
            page, rect = rects[mapping.text_fields[key]]
            draws[page].append(("text", rect, value))

    text("head_of_household_name", content.head_of_household_name)
    text("other_household_members", content.other_household_members)
    text("member_id", content.member_id)
    text("phone", content.phone)
    text("todays_date", content.todays_date)
    text("expected_annual_income", content.expected_annual_income)
    text("other_income_source", content.other_income_source)
    if stamp is not None:
        text("signature_date", stamp.signature_date)

    for key, value in (("income_detail", content.income_detail), ("explanation", content.explanation)):
        if value:
            page, rect = rects[mapping.multiline_fields[key]]
            draws[page].append(("multiline", rect, value))

    checks = list(content.income_types)
    if content.reason == "cannot_access":
        checks.append("reason_cannot_access")
    elif content.reason == "does_not_exist":
        checks.append("reason_does_not_exist")
    for key in checks:
        page, rect = rects[mapping.checkboxes[key]]
        draws[page].append(("check", rect, ""))

    for i in range(n_pages):
        width, height = sizes[i]
        c.setPageSize((width, height))
        _header(c, width, height, stamp)
        for kind, rect, value in draws[i]:
            if kind == "text":
                _draw_text(c, rect, value)
            elif kind == "multiline":
                _draw_multiline(c, rect, value)
            else:
                _draw_check(c, rect)
        if stamp is not None and int(mapping.signature_line.get("page", 0)) - 1 == i:
            _draw_signature(c, mapping.signature_line, stamp)
        _watermark(c, width, height)
        c.showPage()
    c.save()
    buf.seek(0)
    overlay = PdfReader(buf)

    writer = PdfWriter(clone_from=reader)
    for i, page in enumerate(writer.pages):
        page.merge_page(overlay.pages[i])
    # Flatten: drop every widget (fields, Print/Clear buttons with their scripts) and the form.
    writer.remove_annotations(subtypes="/Widget")
    root = writer._root_object
    for key in ("/AcroForm", "/OpenAction"):
        if NameObject(key) in root:
            del root[NameObject(key)]
    writer.add_metadata({"/Title": f"{mapping.title} ({WATERMARK})", "/Producer": "MassHelp"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path


def _draw_text(c: rl_canvas.Canvas, rect: tuple[float, float, float, float], value: str) -> None:
    x0, y0, x1, y1 = rect
    size = 10.0
    available = (x1 - x0) - 6
    while size > 6 and c.stringWidth(value, "Helvetica", size) > available:
        size -= 0.5
    c.setFont("Helvetica", size)
    c.setFillColor(colors.HexColor("#0b2a6f"))
    c.drawString(x0 + 3, y0 + max((y1 - y0 - size) / 2, 2) + 1, value)


def _draw_multiline(c: rl_canvas.Canvas, rect: tuple[float, float, float, float], value: str) -> None:
    x0, y0, x1, y1 = rect
    style = ParagraphStyle("field", fontName="Helvetica", fontSize=10, leading=12.5,
                           textColor=colors.HexColor("#0b2a6f"))
    paragraphs = [Paragraph(escape(part).replace("\n", "<br/>"), style) for part in value.split("\n\n")]
    frame = Frame(x0, y0, x1 - x0, y1 - y0, leftPadding=3, rightPadding=3, topPadding=2, bottomPadding=2,
                  showBoundary=0)
    frame.addFromList([KeepInFrame(x1 - x0 - 6, y1 - y0 - 4, paragraphs, mode="shrink")], c)


def _draw_check(c: rl_canvas.Canvas, rect: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = rect
    size = max(min(x1 - x0, y1 - y0) + 1, 7)
    c.setFont("ZapfDingbats", size)
    c.setFillColor(colors.HexColor("#0b2a6f"))
    c.drawCentredString((x0 + x1) / 2, y0 + 0.5, "4")  # check mark


def _draw_signature(c: rl_canvas.Canvas, line: dict, stamp: FinalStamp) -> None:
    how = "by phone" if stamp.channel == "voice" else "by text message"
    c.setFillColor(colors.HexColor("#0b2a6f"))
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(line["x"], line["y"] + 8, f"{stamp.signer_name} (agreed {how} through MassHelp)")
    c.setFont("Helvetica", 6.5)
    c.drawString(line["x"], line["y"], f"Consent {stamp.consent_id}, {stamp.consented_at}")


def _header(c: rl_canvas.Canvas, width: float, height: float, stamp: FinalStamp | None) -> None:
    c.setFillColor(colors.HexColor("#b00020"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(36, height - 16, HEADER_NOTE)
    if stamp is not None and stamp.receipt_number:
        c.setFont("Helvetica", 7.5)
        c.drawString(36, height - 26, f"Mock receipt number: {stamp.receipt_number}. Not sent to MassHealth.")


def _watermark(c: rl_canvas.Canvas, width: float, height: float) -> None:
    c.saveState()
    c.setFillColor(colors.HexColor("#d0021b"))
    c.setFillAlpha(0.16)
    c.setFont("Helvetica-Bold", 46)
    c.translate(width / 2, height / 2)
    c.rotate(40)
    c.drawCentredString(0, 0, WATERMARK)
    c.restoreState()


# ---------------------------------------------------------------- text helpers


def us_date(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def us_phone(e164: str | None) -> str:
    digits = (e164 or "").lstrip("+")
    if len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return e164 or ""


def money(value: float) -> str:
    return f"${value:,.2f}"
