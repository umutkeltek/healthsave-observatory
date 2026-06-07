"""DOCS-001: the README roadmap must not list shipped analysis jobs as "not yet
included". Weekly summaries and cross-metric correlation analysis are
implemented (engine.run_weekly_summary / run_correlation_analysis) and
scheduled, so they must not appear in the "not yet" line.
"""

from __future__ import annotations

from pathlib import Path

_README = Path(__file__).resolve().parents[1] / "README.md"


def _roadmap_not_yet_line() -> str:
    for line in _README.read_text().splitlines():
        low = line.lower()
        if "not" in low and "yet" in low and "includ" in low:
            return low
    raise AssertionError("expected a 'not yet included' roadmap line in README.md")


def test_readme_does_not_list_weekly_summaries_as_roadmap():
    assert "weekly summ" not in _roadmap_not_yet_line()


def test_readme_does_not_list_correlation_analysis_as_roadmap():
    assert "correlation" not in _roadmap_not_yet_line()
