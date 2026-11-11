"""Reproducible descriptions, with explicit limits on medical interpretation.

The cited source supports how reference ranges are read. It does not validate
diagnostic rules. No disease, treatment, risk score, or clinical certainty is
inferred from a result or from a user confirming an extraction.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from contracts.lab_imports import (
    LabEvidenceSource,
    LabImportReport,
    LabReportComparison,
    LabReportResult,
)
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


@dataclass(frozen=True)
class LabHistoryPoint:
    loinc: str
    lab: str
    unit: str
    specimen_at: datetime
    value: float
    comparator: str | None
    quality_flags: tuple[str, ...]


def _comparison(
    row: NormalizedLabResult, history: list[LabHistoryPoint]
) -> LabReportComparison | None:
    if row.value_comparator or "unit_unreconciled" in row.quality_flags:
        return None
    prior = [
        item
        for item in history
        if item.loinc == row.loinc_code
        and item.lab == row.lab_name
        and item.unit == row.canonical_unit
        and item.specimen_at < row.specimen_at
        and item.comparator is None
        and "unit_unreconciled" not in item.quality_flags
    ]
    if not prior:
        return None
    # A confirmed correction in this import supersedes the old value at the
    # same sample time when computing the report's comparison.
    previous = max(enumerate(prior), key=lambda pair: (pair[1].specimen_at, pair[0]))[1]
    change = row.numeric_value - previous.value
    return LabReportComparison(
        previous_specimen_at=previous.specimen_at,
        previous_value=previous.value,
        absolute_change=change,
        percent_change=change / abs(previous.value) * 100 if previous.value != 0 else None,
    )


def build_report(
    *,
    document_id: UUID,
    file_name: str,
    sha256: str,
    imported_at: datetime,
    results: list[NormalizedLabResult],
    history: list[LabHistoryPoint] | None = None,
) -> LabImportReport:
    candidates = list(history or []) + [
        LabHistoryPoint(
            loinc=item.loinc_code,
            lab=item.lab_name,
            unit=item.canonical_unit,
            specimen_at=item.specimen_at,
            value=item.numeric_value,
            comparator=item.value_comparator,
            quality_flags=item.quality_flags,
        )
        for item in results
    ]
    # Persistence identity excludes unit/value. A corrected censored or unknown-
    # unit row must remove the former exact value before eligibility filtering.
    comparison_history = list(
        {(item.loinc, item.lab, item.specimen_at): item for item in candidates}.values()
    )
    items = []
    for row in results:
        comparison = _comparison(row, comparison_history)
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
                personal_pattern=(
                    f"Change of {comparison.absolute_change:+.4g} {row.canonical_unit} "
                    f"from {comparison.previous_value:.4g} on "
                    f"{comparison.previous_specimen_at.isoformat()} in this lab. "
                    "A numerical change does not establish its cause or medical importance."
                    if comparison
                    else "No comparable earlier result in this lab was available for this report. "
                    "One measurement does not establish a trend."
                ),
                medical_evidence="Educational context only; no diagnosis or treatment inference.",
                source_page=row.provenance.get("source_page"),
                source_excerpt=row.provenance.get("source_excerpt"),
                quality_flags=list(row.quality_flags),
                source_ids=["medlineplus-lab-results"],
                comparison=comparison,
            )
        )
    return LabImportReport(
        id=document_id,
        file_name=file_name,
        sha256=sha256,
        imported_at=imported_at,
        report_version="lab-record-2",
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
