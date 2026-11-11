"""Reproducible descriptions, with explicit limits on medical interpretation.

The cited source supports how reference ranges are read. It does not validate
diagnostic rules. No disease, treatment, risk score, or clinical certainty is
inferred from a result or from a user confirming an extraction.
"""

from datetime import datetime
from uuid import UUID

from contracts.lab_imports import LabEvidenceSource, LabImportReport, LabReportResult
from normalization.labs import NormalizedLabResult

SOURCES = [
    LabEvidenceSource(
        id="medlineplus-lab-results",
        title="How to Understand Your Lab Results — MedlinePlus, National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/how-to-understand-your-lab-results/",
        accessed_on="2026-11-11",
        scope="Lab-specific ranges, measurement differences, and interpretation limits.",
    )
]


def build_report(
    *,
    document_id: UUID,
    file_name: str,
    sha256: str,
    imported_at: datetime,
    results: list[NormalizedLabResult],
) -> LabImportReport:
    items = []
    for row in results:
        if row.value_comparator:
            observation = "Reported as a limit; an exact value and range position are not known."
        elif "unit_unreconciled" in row.quality_flags:
            observation = (
                "Unit kept as written; range interpretation is withheld until the unit is verified."
            )
        elif row.reference_low is not None and row.numeric_value < row.reference_low:
            observation = "Below this laboratory's printed reference range."
        elif row.reference_high is not None and row.numeric_value > row.reference_high:
            observation = "Above this laboratory's printed reference range."
        elif row.reference_low is not None and row.reference_high is not None:
            observation = "Within this laboratory's printed reference range."
        elif row.reference_low is not None or row.reference_high is not None:
            observation = "Meets the one-sided reference limit provided by this laboratory."
        else:
            observation = "No laboratory reference range was supplied."
        items.append(
            LabReportResult(
                marker=row.marker_name or row.loinc_code,
                loinc=row.loinc_code,
                specimen_at=row.specimen_at,
                lab=row.lab_name,
                value=row.numeric_value,
                comparator=row.value_comparator,
                unit=row.canonical_unit,
                reference_low=row.reference_low,
                reference_high=row.reference_high,
                observation=observation,
                measurement_quality="Transcription checked by importer; lab accuracy not assessed.",
                personal_pattern="One import does not establish a trend. Compare history in Labs.",
                medical_evidence="Educational context only; no diagnosis or treatment inference.",
                source_page=row.provenance.get("source_page"),
                source_excerpt=row.provenance.get("source_excerpt"),
                quality_flags=list(row.quality_flags),
                source_ids=["medlineplus-lab-results"],
            )
        )
    return LabImportReport(
        id=document_id,
        file_name=file_name,
        sha256=sha256,
        imported_at=imported_at,
        report_version="lab-record-1",
        review_status="Descriptive record; not clinically validated.",
        limitations=[
            "An out-of-range value alone does not establish disease; "
            "an in-range value does not guarantee health.",
            "Ranges and methods can differ between laboratories. "
            "Results are not averaged across labs.",
            "Clinical interpretation requires medical history and professional review. "
            "This report does not assess urgency.",
            "Originals and reviewed records are retained privately on this Observatory.",
        ],
        results=items,
        sources=SOURCES,
    )
