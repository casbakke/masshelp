from pathlib import Path

from pypdf import PdfReader

from masshelp.forms.afvi import AfviContent, FinalStamp, check_template, default_mapping, render_afvi


def content() -> AfviContent:
    return AfviContent(head_of_household_name="Maria Santos", member_id="MH-DEMO-000123", phone="(617) 555-0101",
                       todays_date="12/01/2026", expected_annual_income="10,800.00", reason="does_not_exist",
                       income_types=["self_employment_income"], income_detail="Self-employment income: $900 a month.",
                       explanation="This is for the MassHealth work rule check for November 2026.")


def test_mapping_matches_template():
    assert check_template(default_mapping()) == []


def test_render_is_flat_and_watermarked(tmp_path: Path):
    out = render_afvi(content(), tmp_path / "a.pdf", stamp=FinalStamp(
        signer_name="Maria Santos", channel="voice", consent_id="consent_1", consented_at="12/01/2026 15:00 UTC",
        signature_date="12/01/2026", receipt_number="MOCK-RCPT-12345"))
    reader = PdfReader(out)
    assert len(reader.pages) == 2
    assert not reader.get_fields()  # flattened, no Print/Clear scripts
    text = "".join(p.extract_text() for p in reader.pages)
    for s in ("Maria Santos", "MH-DEMO-000123", "SAMPLE - NOT FOR SUBMISSION", "MOCK-RCPT-12345", "consent_1"):
        assert s in text
    assert text.count("SAMPLE - NOT FOR SUBMISSION") >= 2  # every page (R31)


def test_demo_fixed_pdf(services, tmp_path):
    from masshelp.forms.build import BuiltForm, write_pdf
    from masshelp.store.models import Case

    fixed = tmp_path / "fixed.pdf"
    fixed.write_bytes(b"%PDF-1.4 fixed")
    services.settings.demo_fixed_pdf = fixed
    with services.db.session() as s:
        case = Case(phone_e164="+1")
        s.add(case)
        s.commit()
        pdf = write_pdf(services, s, case, BuiltForm(content(), {}, {}, "h"), kind="draft")
    assert Path(pdf.path).read_bytes() == b"%PDF-1.4 fixed"
