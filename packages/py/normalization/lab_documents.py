"""Local document extraction. Every proposed field remains subject to review."""

from __future__ import annotations

import csv
import io
import os
import re
import selectors
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from contracts._base import DEFAULT_OWNER_ID
from contracts.lab_imports import LabDocumentPage, LabReviewRow

from .labs import MARKER_CATALOG, LabCsvParse, parse_lab_csv

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_PAGES = 12
MAX_TEXT = 150_000
MAX_ROWS = 250
FIELDS = (
    "specimen_datetime",
    "loinc",
    "marker_name",
    "value",
    "unit",
    "reference_low",
    "reference_high",
    "lab",
    "panel",
)
_NUMBER = r"(?:<=|>=|[<>≤≥])?[+-]?\d+(?:[.,]\d+)?"
_ALIASES = {m.name.casefold(): m.loinc for m in MARKER_CATALOG.values()}
_ALIASES.update(
    {
        "haemoglobin": "718-7",
        "hemoglobin": "718-7",
        "hgb": "718-7",
        "hba1c": "4548-4",
        "25-oh vitamin d": "1989-3",
        "ldl cholesterol": "13457-7",
    }
)
# A generic analyte label can accompany either explicitly printed measurement
# code. This does not convert between their units or choose a missing code.
_RELATED_CODES = ({"2345-7", "14749-6"}, {"4548-4", "59261-8"})


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[LabDocumentPage]
    rows: list[LabReviewRow]
    warnings: list[str]
    evidence: dict[str, dict]


def _csv_document(content: bytes) -> ExtractedDocument:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Save the CSV as UTF-8 before importing it.") from exc
    if "\x00" in text:
        raise ValueError("The CSV contains invalid binary data.")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip().lower() for h in reader.fieldnames or []]
    if len(set(headers)) != len(headers) or not headers or any(h not in FIELDS for h in headers):
        raise ValueError(
            "CSV headers must use the lab template, with no repeated or unknown columns."
        )
    reader.fieldnames = headers
    rows, evidence = [], {}
    for cells in reader:
        if None in cells:
            raise ValueError(f"CSV row {reader.line_num} has too many columns.")
        if not any(cells.values()):
            continue
        row_id = f"csv-{reader.line_num}"
        rows.append(
            LabReviewRow(row_id=row_id, **{k: (cells.get(k) or "").strip() for k in FIELDS})
        )
        evidence[row_id] = {
            "source_page": 1,
            "source_excerpt": " | ".join(v or "" for v in cells.values()),
        }
        if len(rows) > MAX_ROWS:
            raise ValueError(f"Import at most {MAX_ROWS} results at a time.")
    if not rows:
        raise ValueError("The CSV has no result rows.")
    return ExtractedDocument(
        [LabDocumentPage(page=1, text=text[:MAX_TEXT], method="csv")],
        rows,
        ["Check every value, unit, sample date and lab range before confirming."],
        evidence,
    )


def _run(command: list[str], deadline: float) -> str:
    if deadline <= time.monotonic():
        raise ValueError("This PDF took too long to read. Split it into smaller documents.")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Local PDF tools are unavailable. Install Poppler and Tesseract."
        ) from exc
    output = bytearray()
    command_deadline = min(deadline, time.monotonic() + 20)
    try:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= command_deadline:
                    raise ValueError(
                        "This PDF took too long to read. Split it into smaller documents."
                    )
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        break
                    output.extend(chunk)
                    if len(output) > MAX_TEXT * 4:
                        raise ValueError(
                            "The document contains too much text. Split it into smaller files."
                        )
        try:
            result = process.wait(timeout=max(0.01, command_deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "This PDF took too long to read. Split it into smaller documents."
            ) from exc
        if result:
            raise ValueError("The PDF could not be read. Export an unlocked PDF or use CSV.")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout:
            process.stdout.close()
    return output.decode("utf-8", errors="replace")


def _pdf_document(content: bytes) -> ExtractedDocument:
    if not content.startswith(b"%PDF-"):
        raise ValueError("This file does not contain a PDF.")
    deadline = time.monotonic() + 90
    pages: list[LabDocumentPage] = []
    with tempfile.TemporaryDirectory(prefix="healthsave-lab-") as directory:
        source = Path(directory) / "source.pdf"
        source.write_bytes(content)
        info = _run(["pdfinfo", str(source)], deadline)
        match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
        if not match or not 1 <= int(match[1]) <= MAX_PAGES:
            raise ValueError(f"Import a PDF with 1–{MAX_PAGES} pages.")
        if re.search(r"^Encrypted:\s+yes", info, re.MULTILINE):
            raise ValueError("Export an unlocked PDF before importing it.")
        for page in range(1, int(match[1]) + 1):
            text = _run(
                [
                    "pdftotext",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-layout",
                    "-enc",
                    "UTF-8",
                    str(source),
                    "-",
                ],
                deadline,
            )
            method = "text"
            if len(text.strip()) < 30:
                if not shutil.which("tesseract"):
                    raise RuntimeError("Scanned PDFs require local Tesseract OCR.")
                image = str(Path(directory) / f"page-{page}")
                _run(
                    [
                        "pdftoppm",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-singlefile",
                        "-scale-to",
                        "1800",
                        "-png",
                        str(source),
                        image,
                    ],
                    deadline,
                )
                text = _run(["tesseract", image + ".png", "stdout", "--psm", "6"], deadline)
                method = "ocr"
            pages.append(LabDocumentPage(page=page, text=text.strip(), method=method))
            if sum(len(p.text) for p in pages) > MAX_TEXT:
                raise ValueError("The PDF contains too much text. Split it into smaller files.")
    rows, evidence = [], {}
    conflicts = []
    for page in pages:
        for number, raw in enumerate(page.text.splitlines(), 1):
            line = " ".join(raw.split())
            code = re.search(r"\b(\d{1,7}-\d)\b", line)
            loinc = code[1] if code and code[1] in MARKER_CATALOG else None
            label = None
            for alias in sorted(_ALIASES, key=len, reverse=True):
                if re.match(re.escape(alias) + r"(?=\s|:|$)", line, re.IGNORECASE):
                    label = alias
                    loinc = loinc or _ALIASES[alias]
                    break
            if not loinc:
                continue
            if label and code and code[1] in MARKER_CATALOG:
                named_code = _ALIASES[label]
                if named_code != loinc and not any(
                    {named_code, loinc} <= family for family in _RELATED_CODES
                ):
                    conflicts.append(f"Page {page.page}, line {number}")
                    continue
            tail = line[len(label) :] if label else line[code.end() :]
            if code and code[1] in MARKER_CATALOG:
                tail = tail.replace(code[1], "", 1)
            tail = tail.strip(" :\t")
            candidate = re.match(
                rf"({_NUMBER})\s+(?:(?:H|L|HIGH|LOW|\*{{1,2}})\s+)?"
                rf"([^\s]+)(?:\s+({_NUMBER})\s*[-–]\s*({_NUMBER}))?",
                tail,
                re.IGNORECASE,
            )
            if not candidate:
                continue
            row_id = f"p{page.page}-l{number}"
            rows.append(
                LabReviewRow(
                    row_id=row_id,
                    loinc=loinc,
                    marker_name=MARKER_CATALOG[loinc].name,
                    value=candidate[1].replace("≤", "<=").replace("≥", ">="),
                    unit=candidate[2],
                    reference_low=candidate[3] or "",
                    reference_high=candidate[4] or "",
                )
            )
            evidence[row_id] = {"source_page": page.page, "source_excerpt": line[:2000]}
    if len(rows) > MAX_ROWS:
        raise ValueError(f"Import at most {MAX_ROWS} results at a time.")
    warnings = [
        "Extraction is a draft, not a verified result. Compare every field with the original PDF.",
        "Enter the sample date and performing lab. Add missing markers manually.",
        "Some results may not be detected. Check that every result you want is included.",
    ]
    if conflicts:
        warnings.append(
            "Skipped lines with conflicting test names and LOINC codes: "
            + "; ".join(conflicts)
            + ". Check the original and enter the correct test manually."
        )
    if any(p.method == "ocr" for p in pages):
        warnings.append(
            "Local OCR was used. Pay particular attention to decimal points, signs and units."
        )
    return ExtractedDocument(pages, rows, warnings, evidence)


def extract_document(content: bytes, file_name: str) -> ExtractedDocument:
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Choose a non-empty file no larger than 5 MB.")
    extension = Path(file_name).suffix.lower()
    if extension == ".csv":
        try:
            return _csv_document(content)
        except csv.Error as exc:
            raise ValueError(
                "The CSV has an invalid or oversized field. Use the lab template."
            ) from exc
    if extension == ".pdf":
        return _pdf_document(content)
    raise ValueError("Choose a CSV or PDF file.")


def validate_review(rows: list[LabReviewRow], *, now: datetime | None = None) -> LabCsvParse:
    if not rows or len(rows) > MAX_ROWS:
        raise ValueError(f"Review between 1 and {MAX_ROWS} results.")
    if any(not r.confirmed for r in rows):
        raise ValueError("Explicitly confirm every result before saving.")
    if len({r.row_id for r in rows}) != len(rows):
        raise ValueError("Each reviewed row must have a unique identity.")
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: getattr(row, key) for key in FIELDS})
    parsed = parse_lab_csv(
        out.getvalue().encode(),
        owner_id=DEFAULT_OWNER_ID,
        file_name="reviewed.csv",
        now=now or datetime.now(UTC),
    )
    # A confirmation must not silently drop rows with different ranges or labels.
    if parsed.duplicates_collapsed:
        raise ValueError(
            "Repeated results share a lab, test and sample date. Keep one reviewed row."
        )
    return parsed
