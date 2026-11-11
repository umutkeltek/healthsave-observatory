"""Import actual files through the review boundary; no patient data."""

import shutil
import subprocess
import sys
import time
import zlib
from datetime import UTC, datetime

import pytest
from contracts.lab_imports import LabReviewRow
from normalization.lab_documents import extract_document, validate_review
from normalization.labs import LabCsvValidationError

CSV = (
    b"specimen_datetime,loinc,marker_name,value,unit,reference_low,reference_high,lab\n"
    b"2026-01-02,2276-4,Ferritin,12,ng/mL,20,200,Example Lab\n"
)
NOW = datetime(2026, 11, 11, tzinfo=UTC)


def test_csv_review_requires_explicit_confirmation():
    extracted = extract_document(CSV, "results.csv")
    assert extracted.rows[0].confirmed is False
    with pytest.raises(ValueError, match="confirm"):
        validate_review(extracted.rows, now=NOW)
    confirmed = [r.model_copy(update={"confirmed": True}) for r in extracted.rows]
    parsed = validate_review(confirmed, now=NOW)
    assert parsed.results[0].numeric_value == 12
    assert parsed.results[0].reference_low == 20


def test_edits_are_revalidated_and_unknown_fields_not_guessed():
    rows = extract_document(CSV, "results.csv").rows
    bad = rows[0].model_copy(update={"confirmed": True, "unit": "mmol/L"})
    with pytest.raises(LabCsvValidationError):
        validate_review([bad], now=NOW)
    blank = LabReviewRow(row_id="manual-1", marker_name="Ferritin", confirmed=True)
    with pytest.raises(LabCsvValidationError):
        validate_review([blank], now=NOW)


def test_csv_formula_and_nonfinite_values_never_become_measurements():
    row = extract_document(CSV, "results.csv").rows[0]
    for value in ("=1+1", "NaN", "Infinity"):
        with pytest.raises(LabCsvValidationError):
            validate_review([row.model_copy(update={"confirmed": True, "value": value})], now=NOW)


def test_duplicate_row_identity_is_rejected():
    row = extract_document(CSV, "results.csv").rows[0].model_copy(update={"confirmed": True})
    with pytest.raises(ValueError, match="identity"):
        validate_review([row, row], now=NOW)


def test_file_type_and_content_are_checked():
    with pytest.raises(ValueError):
        extract_document(b"<html>not a PDF</html>", "report.pdf")
    with pytest.raises(ValueError):
        extract_document(CSV, "report.exe")
    with pytest.raises(ValueError):
        extract_document(b"", "empty.csv")


def test_oversized_csv_field_is_a_validation_error():
    with pytest.raises(ValueError, match="oversized"):
        extract_document(b"marker_name\n" + b"x" * 140_000, "large.csv")


def pdf_bytes(objects: list[bytes]) -> bytes:
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        body.extend(f"{offset:010} 00000 n \n".encode())
    body.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(body)


def text_pdf(lines: list[str]) -> bytes:
    stream = (
        b"BT /F1 18 Tf 40 740 Td "
        + b" 0 -30 Td ".join(b"(" + line.encode() + b") Tj" for line in lines)
        + b" ET"
    )
    return pdf_bytes(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        ]
    )


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="local Poppler required")
def test_actual_text_pdf_preserves_comparators_and_explicit_codes():
    extracted = extract_document(
        text_pdf(
            [
                "Synthetic lab report - not a patient",
                "Ferritin <=12 ng/mL 20-200",
                "Ferritin 2276-4 12 ng/mL 20-200",
                "Glucose 14749-6 5.2 mmol/L 3.9-5.6",
            ]
        ),
        "synthetic.pdf",
    )
    assert [(r.loinc, r.value, r.unit) for r in extracted.rows] == [
        ("2276-4", "<=12", "ng/mL"),
        ("2276-4", "12", "ng/mL"),
        ("14749-6", "5.2", "mmol/L"),
    ]
    assert extracted.pages[0].method == "text"
    assert all(not r.confirmed and r.specimen_datetime == "" for r in extracted.rows)
    assert extracted.evidence[extracted.rows[-1].row_id]["source_page"] == 1


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="local Poppler required")
@pytest.mark.parametrize("flag", ["L", "H", "LOW", "HIGH", "*", "**"])
def test_pdf_result_flags_do_not_replace_units_or_ranges(flag):
    extracted = extract_document(text_pdf([f"Ferritin 12 {flag} ng/mL 20-200"]), "flags.pdf")
    row = extracted.rows[0]
    assert (row.value, row.unit, row.reference_low, row.reference_high) == (
        "12",
        "ng/mL",
        "20",
        "200",
    )
    assert not row.confirmed


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="local Poppler required")
def test_pdf_conflicting_test_identity_requires_manual_resolution():
    extracted = extract_document(
        text_pdf(["Hemoglobin 2276-4 12 ng/mL 20-200", "HbA1c 59261-8 42 mmol/mol 20-42"]),
        "conflict.pdf",
    )
    assert [(row.loinc, row.value) for row in extracted.rows] == [("59261-8", "42")]
    assert any("conflicting" in warning and "Page 1" in warning for warning in extracted.warnings)


@pytest.mark.skipif(
    not shutil.which("tesseract") or not shutil.which("pdftoppm"), reason="local OCR tools required"
)
def test_actual_scanned_pdf_uses_local_ocr(tmp_path):
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(text_pdf(["Synthetic laboratory report", "Ferritin 12 ng/mL 20-200"]))
    prefix = tmp_path / "scan"
    subprocess.run(
        ["pdftoppm", "-singlefile", "-scale-to", "1800", str(source), str(prefix)],
        check=True,
        capture_output=True,
        timeout=20,
    )
    ppm = prefix.with_suffix(".ppm").read_bytes()
    magic, dimensions, depth, pixels = ppm.split(b"\n", 3)
    assert magic == b"P6" and depth == b"255"
    width, height = dimensions.split()
    compressed = zlib.compress(pixels)
    draw = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    scanned = pdf_bytes(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /XObject /Subtype /Image /Width "
            + width
            + b" /Height "
            + height
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
            + str(len(compressed)).encode()
            + b" >>\nstream\n"
            + compressed
            + b"\nendstream",
            f"<< /Length {len(draw)} >>\nstream\n".encode() + draw + b"\nendstream",
        ]
    )
    extracted = extract_document(scanned, "scan.pdf")
    assert extracted.pages[0].method == "ocr"
    assert extracted.rows[0].value == "12"
    assert any("OCR" in w for w in extracted.warnings)
    assert not extracted.rows[0].confirmed


def test_subprocess_output_and_duration_are_bounded():
    from normalization.lab_documents import _run

    with pytest.raises(ValueError, match="too much text"):
        _run(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 700000)"],
            time.monotonic() + 5,
        )
    with pytest.raises(ValueError, match="too long"):
        _run([sys.executable, "-c", "import time; time.sleep(10)"], time.monotonic() + 0.1)
