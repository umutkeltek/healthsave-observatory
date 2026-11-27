from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from analysis.statistical.lab_reports import LabHistoryPoint, build_report
from normalization.lab_documents import extract_document, validate_review

from tests.test_lab_document_review import CSV, NOW


def test_report_compares_only_prior_exact_results_in_the_same_lab_and_unit():
    row = extract_document(CSV, "example.csv").rows[0].model_copy(update={"confirmed": True})
    result = validate_review([row], now=NOW).results[0]
    previous = LabHistoryPoint(
        "2276-4",
        "Example Lab",
        "ng/mL",
        datetime(2025, 12, 1, tzinfo=UTC),
        10,
        None,
        (),
    )
    history = [
        previous,
        replace(previous, lab="Another Lab", value=40),
        replace(previous, unit="unknown", value=50, specimen_at=datetime(2025, 12, 5, tzinfo=UTC)),
        replace(previous, specimen_at=datetime(2026, 4, 1, tzinfo=UTC), value=60),
        replace(previous, comparator="<", value=70, specimen_at=datetime(2025, 12, 6, tzinfo=UTC)),
    ]
    report = build_report(
        document_id=uuid4(),
        file_name="example.csv",
        sha256="a" * 64,
        imported_at=NOW,
        results=[result],
        history=history,
    )
    comparison = report.results[0].comparison
    assert comparison.previous_value == 10
    assert comparison.absolute_change == 2
    assert comparison.percent_change == pytest.approx(20)
    assert "does not establish its cause" in report.results[0].personal_pattern
    censored = build_report(
        document_id=uuid4(),
        file_name="example.csv",
        sha256="a" * 64,
        imported_at=NOW,
        results=[replace(result, value_comparator="<")],
        history=history,
    )
    assert censored.results[0].comparison is None


def test_zero_previous_value_never_generates_an_infinite_percentage():
    row = extract_document(CSV, "example.csv").rows[0].model_copy(update={"confirmed": True})
    result = validate_review([row], now=NOW).results[0]
    previous = LabHistoryPoint(
        "2276-4", "Example Lab", "ng/mL", datetime(2025, 12, 1, tzinfo=UTC), 0, None, ()
    )
    report = build_report(
        document_id=uuid4(),
        file_name="example.csv",
        sha256="a" * 64,
        imported_at=NOW,
        results=[result],
        history=[previous],
    )
    assert report.results[0].comparison.percent_change is None


@pytest.mark.parametrize(
    "changes",
    [
        {"value_comparator": "<", "numeric_value": 5},
        {"canonical_unit": "unknown", "quality_flags": ("unit_unreconciled",)},
    ],
)
def test_same_import_corrections_remove_obsolete_comparable_values(changes):
    row = extract_document(CSV, "example.csv").rows[0].model_copy(update={"confirmed": True})
    current = validate_review([row], now=NOW).results[0]
    old_date = datetime(2025, 12, 1, tzinfo=UTC)
    obsolete = LabHistoryPoint("2276-4", "Example Lab", "ng/mL", old_date, 10, None, ())
    corrected = replace(current, specimen_at=old_date, **changes)
    report = build_report(
        document_id=uuid4(),
        file_name="example.csv",
        sha256="a" * 64,
        imported_at=NOW,
        results=[corrected, current],
        history=[obsolete],
    )
    assert report.results[1].comparison is None


def test_lab_spelling_uses_the_same_identity_for_corrections_and_comparisons():
    row = extract_document(CSV, "example.csv").rows[0].model_copy(update={"confirmed": True})
    latest = validate_review([row], now=NOW).results[0]
    previous = replace(
        latest,
        lab_name="  EXAMPLE   LAB ",
        specimen_at=datetime(2025, 12, 1, tzinfo=UTC),
        numeric_value=10,
    )
    report = build_report(
        document_id=uuid4(),
        file_name="example.csv",
        sha256="a" * 64,
        imported_at=NOW,
        results=[previous, latest],
    )
    assert report.results[1].comparison.previous_value == 10
    correction = replace(previous, lab_name="Example Lab", value_comparator="<", numeric_value=5)
    report = build_report(
        document_id=uuid4(),
        file_name="example.csv",
        sha256="a" * 64,
        imported_at=NOW,
        results=[previous, correction, latest],
    )
    assert report.results[-1].comparison is None
