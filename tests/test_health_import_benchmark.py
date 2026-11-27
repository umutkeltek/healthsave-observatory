"""The independent benchmark must fail honestly and disclose unexecuted checks."""

import json
import sys

import pytest

from scripts import benchmark_health_imports as benchmark


def test_fixed_non_pdf_cases_and_pdf_skips_are_reported(monkeypatch):
    monkeypatch.setattr(benchmark.shutil, "which", lambda name: None)
    report = benchmark.run_benchmark()
    assert report["counts"] == {"passed": 38, "failed": 0, "skipped": 12}
    assert report["clinical_review"] == "not_performed"
    assert "not measure diagnostic accuracy" in benchmark.markdown(report)


def test_wrong_expected_result_fails_without_rewriting_expectations(tmp_path):
    manifest = json.loads(benchmark.CASES.read_bytes())
    manifest["labs"][0]["expected"]["value"] = 999
    path = tmp_path / "cases.json"
    original = json.dumps(manifest)
    path.write_text(original)
    report = benchmark.run_benchmark(cases_path=path, include_pdf=False)
    assert report["counts"]["failed"] == 1
    failure = next(row for row in report["results"] if row["status"] == "failed")
    assert failure["failed_fields"] == ["value"]
    assert path.read_text() == original


@pytest.mark.parametrize(
    "required,failed,skipped,exit_code",
    [
        (False, 1, 0, 1),
        (False, 0, 12, 0),
        (True, 0, 12, 1),
        (True, 0, 0, 0),
    ],
)
def test_cli_failure_and_required_pdf_exit_codes(monkeypatch, required, failed, skipped, exit_code):
    monkeypatch.setattr(sys, "argv", ["benchmark"] + (["--require-pdf"] if required else []))
    monkeypatch.setattr(
        benchmark,
        "run_benchmark",
        lambda: {
            "counts": {"passed": 33, "failed": failed, "skipped": skipped},
            "results": [],
        },
    )
    assert benchmark.main() == exit_code


def test_empty_case_group_cannot_report_success(tmp_path):
    manifest = json.loads(benchmark.CASES.read_bytes())
    manifest["extraction"] = []
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="extraction"):
        benchmark.run_benchmark(cases_path=path)
