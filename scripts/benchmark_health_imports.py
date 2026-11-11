"""Reproducible synthetic correctness benchmark; never a clinical accuracy score.

Run with the project's Python environment: python -m scripts.benchmark_health_imports
--require-pdf --json /tmp/benchmark.json --markdown /tmp/benchmark.md
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from analysis.statistical.genetics import ENGINE_VERSION, build_genetic_report
from analysis.statistical.lab_reports import build_report
from contracts.lab_imports import LabReviewRow
from normalization.genotypes import parse_genotypes
from normalization.lab_documents import extract_document, validate_review
from normalization.labs import NORMALIZER_VERSION, LabCsvValidationError
from storage.clinvar_reference import ClinvarReferenceStore

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "benchmarks/health-imports/cases.json"
NOW = datetime(2026, 11, 11, tzinfo=UTC)
IDENTIFIER = UUID("11111111-1111-4111-8111-111111111111")


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


def document_pdf(line: str, *, scan: bool = False) -> bytes:
    """Render fixed fixture text; scans contain raster pixels and no text layer."""
    escaped = line.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
    stream = (
        b"BT /F1 18 Tf 40 740 Td (Synthetic benchmark - not a patient) Tj 0 -40 Td ("
        + escaped.encode("ascii")
        + b") Tj ET"
    )
    prefix = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    ]
    text = pdf_bytes(
        prefix
        + [
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        ]
    )
    if not scan:
        return text
    with tempfile.TemporaryDirectory(prefix="healthsave-benchmark-") as directory:
        source, target = Path(directory) / "text.pdf", Path(directory) / "scan"
        source.write_bytes(text)
        subprocess.run(
            ["pdftoppm", "-singlefile", "-scale-to", "1800", str(source), str(target)],
            check=True,
            capture_output=True,
            timeout=20,
        )
        magic, dimensions, depth, pixels = target.with_suffix(".ppm").read_bytes().split(b"\n", 3)
        if magic != b"P6" or depth != b"255":
            raise ValueError("Unexpected synthetic raster format")
    width, height = dimensions.split()
    raster = zlib.compress(pixels)
    draw = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    return pdf_bytes(
        prefix
        + [
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /XObject /Subtype /Image /Width "
            + width
            + b" /Height "
            + height
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
            + str(len(raster)).encode()
            + b" >>\nstream\n"
            + raster
            + b"\nendstream",
            f"<< /Length {len(draw)} >>\nstream\n".encode() + draw + b"\nendstream",
        ]
    )


def equal(actual, expected) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and math.isclose(
            actual, expected, rel_tol=1e-10, abs_tol=1e-10
        )
    return actual == expected


def lab_case(case: dict) -> dict:
    row = LabReviewRow.model_validate(
        {
            "row_id": "manual-benchmark",
            "specimen_datetime": "2026-01-02",
            "loinc": "2276-4",
            "value": "40",
            "unit": "ng/mL",
            "reference_low": "20",
            "reference_high": "200",
            "lab": "Synthetic calibration lab",
            "confirmed": True,
            **case["input"],
        }
    )
    try:
        parsed = validate_review([row], now=NOW)
    except LabCsvValidationError as exc:
        fields = sorted({error.column for error in exc.errors if error.column})
        return {"passed": case.get("reject_field") in fields, "rejected_fields": fields}
    if "reject_field" in case:
        return {"passed": False, "error": "Expected rejection, but input was accepted"}
    report = build_report(
        document_id=IDENTIFIER,
        file_name="synthetic.csv",
        sha256=parsed.file_sha256,
        imported_at=NOW,
        results=parsed.results,
    )
    result = report.results[0]
    observed = result.model_dump(mode="json")
    failed = []
    for key, expected in case["expected"].items():
        correct = (
            result.observation.startswith(expected)
            if key == "observation"
            else set(expected).issubset(result.quality_flags)
            if key == "flags"
            else equal(observed[key], expected)
        )
        if not correct:
            failed.append(key)
    # Every accepted report must retain the source and interpretation boundary.
    if (
        result.source_ids != ["medlineplus-lab-results"]
        or "not clinically validated" not in report.review_status
    ):
        failed.append("interpretation_boundary")
    return {"passed": not failed, "failed_fields": failed, "observed": observed}


def extraction_case(case: dict) -> dict:
    extracted = extract_document(
        document_pdf(case["line"], scan=case.get("scan", False)), "synthetic.pdf"
    )
    actual = [[r.loinc, r.value, r.unit, r.reference_low, r.reference_high] for r in extracted.rows]
    expected = case["expected"]
    correct_fields = sum(
        a == b
        for left, right in zip(actual, expected, strict=False)
        for a, b in zip(left, right, strict=True)
    )
    checks = {
        "rows": actual == expected,
        "requires_review": all(
            not r.confirmed and not r.specimen_datetime and not r.lab for r in extracted.rows
        ),
        "source_location": all(
            extracted.evidence[r.row_id]["source_page"] == 1 for r in extracted.rows
        ),
        "method": extracted.pages[0].method == ("ocr" if case.get("scan") else "text"),
        "warning": not case.get("warning")
        or case["warning"] in " ".join(extracted.warnings).lower(),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "observed": actual,
        "expected_rows": len(expected),
        "observed_rows": len(actual),
        "correct_fields": correct_fields,
        "expected_fields": sum(map(len, expected)),
    }


def genetic_case(case: dict) -> dict:
    content = (
        "##fileformat=VCFv4.2\n##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTHETIC\n"
        f"1\t10\trs1\t{case.get('reference', 'A')}\t{case.get('alternate', 'G')}\t.\t"
        f"{case.get('filter', 'PASS')}\t.\t{case.get('format', 'GT')}\t{case['genotype']}\n"
    ).encode()
    try:
        parsed = parse_genotypes(
            content, "synthetic.vcf", assembly=case.get("assembly", "GRCh38"), forward_strand=True
        )
    except ValueError as exc:
        return {
            "passed": bool(case.get("reject") and case["reject"] in str(exc)),
            "rejection": str(exc),
        }
    if case.get("reject"):
        return {"passed": False, "error": "Expected rejection, but input was accepted"}
    reference = (
        "##fileformat=VCFv4.2\n##fileDate=2026-11-08\n##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t999999991\tA\tG\t.\t.\tGENEINFO=SYNTHETIC:1;"
        f"CLNSIG={case.get('classification', 'Pathogenic')};CLNDN=Synthetic_only;"
        f"CLNREVSTAT={case.get('review', 'reviewed_by_expert_panel')}\n"
    ).encode()
    with tempfile.TemporaryDirectory(prefix="healthsave-benchmark-reference-") as directory:
        path = Path(directory) / "synthetic.vcf.gz"
        path.write_bytes(gzip.compress(reference, mtime=0))
        store = ClinvarReferenceStore(Path(directory) / "index")
        store.install(path, assembly="GRCh38", source_url="https://example.invalid/synthetic-only")
        snapshot, records = store.lookup(
            "GRCh38", [(r.chromosome, r.position) for r in parsed.loci]
        )
        report = build_genetic_report(
            document_id=IDENTIFIER,
            file_name="synthetic.vcf",
            input_sha256=hashlib.sha256(content).hexdigest(),
            parsed=parsed,
            reference=snapshot,
            records=records,
            now=NOW,
        )
    checks = {
        "matches": report.matched_annotations == case["expected_matches"],
        "mismatches": report.reference_mismatch_loci == case.get("mismatches", 0),
        "counts": all(
            report.input_counts[key] == value for key, value in case.get("count", {}).items()
        ),
        "limitations": any("not a diagnosis" in line for line in report.limitations),
    }
    for name, field in (
        ("copies", "alternate_copies"),
        ("stars", "review_stars"),
        ("category", "category"),
    ):
        if name in case:
            checks[name] = bool(
                report.annotations and getattr(report.annotations[0], field) == case[name]
            )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "matched_annotations": report.matched_annotations,
        "input_counts": report.input_counts,
    }


def run_benchmark(*, cases_path: Path = CASES, include_pdf: bool = True) -> dict:
    raw = cases_path.read_bytes()
    manifest = json.loads(raw)
    for group in ("labs", "extraction", "genetics"):
        cases = manifest[group]
        if not cases or len({case["id"] for case in cases}) != len(cases):
            raise ValueError(f"{group} must have non-empty, uniquely identified cases")
    tools = {
        name: shutil.which(name) is not None
        for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract")
    }
    tool_versions = {}
    for name, available in tools.items():
        if available:
            try:
                version = subprocess.run(
                    [name, "--version" if name == "tesseract" else "-v"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                tool_versions[name] = (version.stdout + version.stderr).splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                tool_versions[name] = "version unavailable"
    results = []
    for group, check in (
        ("labs", lab_case),
        ("extraction", extraction_case),
        ("genetics", genetic_case),
    ):
        for case in manifest[group]:
            if group == "extraction" and (not include_pdf or not all(tools.values())):
                result = {
                    "status": "skipped",
                    "reason": "PDF/OCR tools unavailable or PDF checks disabled",
                }
            else:
                try:
                    result = check(case)
                    result["status"] = "passed" if result.pop("passed") else "failed"
                except Exception as exc:
                    result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            results.append({"group": group, "id": case["id"], **result})
    counts = Counter(result["status"] for result in results)
    return {
        "version": manifest["version"],
        "corpus_sha256": hashlib.sha256(raw).hexdigest(),
        "clinical_review": manifest["clinical_review"],
        "provenance": manifest["provenance"],
        "sources": manifest["sources"],
        "evaluated_at": datetime.now(UTC).isoformat(),
        "engine_versions": {"labs": NORMALIZER_VERSION, "genetics": ENGINE_VERSION},
        "tools": tools,
        "tool_versions": tool_versions,
        "python_version": sys.version.split()[0],
        "counts": {key: counts[key] for key in ("passed", "failed", "skipped")},
        "results": results,
    }


def markdown(report: dict) -> str:
    lines = [
        "# Health import engineering benchmark",
        "",
        report["provenance"],
        "",
        "**External clinical review: not performed. "
        "These results do not measure diagnostic accuracy.**",
        "",
        f"Corpus: `{report['version']}` · SHA-256 `{report['corpus_sha256']}`",
        "",
        "| Case group | Passed | Failed | Skipped |",
        "| --- | ---: | ---: | ---: |",
    ]
    for group in ("labs", "extraction", "genetics"):
        count = Counter(row["status"] for row in report["results"] if row["group"] == group)
        lines.append(f"| {group} | {count['passed']} | {count['failed']} | {count['skipped']} |")
    lines += [
        "",
        "Cases cover selected synthetic inputs, not every laboratory layout or population.",
        "Scans use clean generated raster pages; real camera photos, handwriting "
        "and multilingual reports need separate evaluation.",
        "",
        "## Cases",
        "",
        "| Case | Result |",
        "| --- | --- |",
    ]
    lines += [f"| {row['group']}/{row['id']} | {row['status']} |" for row in report["results"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--require-pdf", action="store_true")
    args = parser.parse_args()
    report = run_benchmark()
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if args.markdown:
        args.markdown.write_text(markdown(report))
    print(json.dumps(report["counts"]))
    for result in report["results"]:
        if result["status"] == "failed":
            print(f"FAIL {result['group']}/{result['id']}: {json.dumps(result)}")
    return int(
        bool(report["counts"]["failed"] or (args.require_pdf and report["counts"]["skipped"]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
