"""v2 Labs read endpoints (no database; the lab repository is faked).

Rows come from the synthetic sample CSV run through the real normalizer, so the
routes are exercised on the same shapes an import writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import server
from fastapi.testclient import TestClient
from normalization.labs import parse_lab_csv
from server.api import deps, v2_labs
from server.api.deps import get_session
from storage.timescale.labs import LabResultRow
from storage.timescale.observations import SeriesPoint

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "labs" / "sample_labs.csv"
OWNER = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _sample_rows() -> list[LabResultRow]:
    parsed = parse_lab_csv(SAMPLE.read_bytes(), owner_id=OWNER, now=NOW)
    rows = [
        LabResultRow(
            id=r.id,
            metric_id=r.metric_id,
            loinc_code=r.loinc_code,
            marker_name=r.marker_name,
            numeric_value=r.numeric_value,
            value_comparator=r.value_comparator,
            canonical_unit=r.canonical_unit,
            reference_low=r.reference_low,
            reference_high=r.reference_high,
            reference_text=r.reference_text,
            specimen_at=r.specimen_at,
            lab_name=r.lab_name,
            panel=r.panel,
            source_plugin_id=r.source_plugin_id,
            stream_id=r.stream_id,
            quality_flags=r.quality_flags,
        )
        for r in parsed.results
    ]
    return sorted(rows, key=lambda r: (r.loinc_code, r.specimen_at, r.lab_name))


class _Repo:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[str | None] = []

    async def list_results(self, session, *, loinc_code=None, **_kwargs):
        self.calls.append(loinc_code)
        return [r for r in self.rows if loinc_code is None or r.loinc_code == loinc_code]


WATCH = "7c1f0c52-4c1b-5d0e-9a43-2a7f7d1b9e01"


class _Observations:
    """Resting HR: 30 days before each draw, 60 bpm early on, 64 bpm before Sep."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def query_series(self, session, *, metric_id, start, end, **_kwargs):
        self.calls.append((metric_id, start, end))
        if not self.enabled or metric_id != "vital.resting_heart_rate":
            return []
        value = 64.0 if end.year == 2026 and end.month >= 9 else 60.0
        days = int((end - start).days)
        return [
            SeriesPoint(
                t=start + timedelta(days=offset, hours=6),
                interval_end=start + timedelta(days=offset, hours=6),
                value=value + (offset % 2),
                code=None,
                unit="bpm",
                source_id="s",
                confidence=None,
                stream_id=WATCH,
            )
            for offset in range(days)
        ]


async def _list_streams(_session, _owner, **_kwargs):
    return [
        {
            "id": UUID(WATCH),
            "source_plugin_id": "apple-healthkit-ios",
            "origin_key": "apple watch",
            "device_label": "Apple Watch",
        }
    ]


@pytest.fixture
def observations(monkeypatch):
    fake = _Observations()
    monkeypatch.setattr(v2_labs, "observation_repository", fake)
    monkeypatch.setattr(v2_labs.registry, "list_streams", _list_streams)
    return fake


@pytest.fixture
def repo(monkeypatch, observations):
    fake = _Repo(_sample_rows())
    monkeypatch.setattr(v2_labs, "lab_repository", fake)
    return fake


@pytest.fixture
def client(repo):
    async def fake_session():
        yield object()

    server.app.dependency_overrides[get_session] = fake_session
    try:
        with TestClient(server.app) as c:
            yield c
    finally:
        server.app.dependency_overrides.clear()


def test_overview_lists_markers_newest_first_with_labs(client, repo) -> None:
    response = client.get("/api/v2/labs")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 4
    assert body["result_count"] == 12
    # Newest result first; ferritin and hemoglobin share Sep 17, so by name.
    assert [m["loinc"] for m in body["markers"]] == ["2276-4", "718-7", "4548-4", "1988-5"]
    assert {lab["lab"] for lab in body["labs"]} == {"Harbor Clinical Lab", "Northfield Diagnostics"}
    northfield = next(lab for lab in body["labs"] if lab["lab"] == "Northfield Diagnostics")
    assert northfield["result_count"] == 10
    assert northfield["source_plugin_id"] == "labs-csv"
    assert repo.calls == [None]


def test_marker_keeps_each_lab_and_its_own_range(client) -> None:
    body = client.get("/api/v2/labs/2276-4").json()
    assert body["metric_id"] == "loinc:2276-4"
    assert body["name"] == "Ferritin"
    assert body["display_unit"] == "ng/mL"
    assert body["result_count"] == 4
    assert body["lab_count"] == 2
    values = [(r["lab"], r["value"], r["reference_low"]) for r in body["results"]]
    assert values == [
        ("Northfield Diagnostics", 64.0, 30.0),
        ("Northfield Diagnostics", 41.0, 30.0),
        ("Northfield Diagnostics", 24.0, 30.0),
        ("Harbor Clinical Lab", 19.0, 15.0),
    ]
    assert body["results"][0]["date_only"] is True
    assert body["results"][1]["date_only"] is False


def test_censored_results_carry_their_comparator(client) -> None:
    body = client.get("/api/v2/labs/1988-5").json()
    (crp,) = body["results"]
    assert (crp["comparator"], crp["value"], crp["reference_high"]) == ("<", 0.5, 5.0)
    assert "censored" in crp["quality_flags"]


def test_converted_units_are_reported_in_the_canonical_unit(client) -> None:
    body = client.get("/api/v2/labs/718-7").json()
    harbor = next(r for r in body["results"] if r["lab"] == "Harbor Clinical Lab")
    assert harbor["unit"] == "g/dL"
    assert harbor["value"] == pytest.approx(12.8)
    assert harbor["reference_low"] == pytest.approx(13.0)


def test_malformed_loinc_is_422_and_unknown_marker_is_404(client) -> None:
    bad = client.get("/api/v2/labs/2276-5")
    assert bad.status_code == 422
    assert "check digit" in bad.json()["detail"]
    missing = client.get("/api/v2/labs/2951-2")
    assert missing.status_code == 404


def test_empty_record_is_an_empty_overview(client, repo) -> None:
    repo.rows = []
    body = client.get("/api/v2/labs").json()
    assert body == {"markers": [], "labs": [], "count": 0, "result_count": 0}


def test_labs_routes_require_the_api_key(monkeypatch, repo) -> None:
    monkeypatch.setattr(deps, "API_KEY", "secret-key")

    async def fake_session():
        yield object()

    server.app.dependency_overrides[get_session] = fake_session
    try:
        with TestClient(server.app) as c:
            assert c.get("/api/v2/labs").status_code == 401
            assert c.get("/api/v2/labs", headers={"X-API-Key": "secret-key"}).status_code == 200
    finally:
        server.app.dependency_overrides.clear()


def test_each_result_is_placed_against_its_own_lab_range(client) -> None:
    body = client.get("/api/v2/labs/2276-4").json()
    bands = [(r["lab"], r["value"], r["band"]) for r in body["results"]]
    assert bands == [
        ("Northfield Diagnostics", 64.0, "within"),
        ("Northfield Diagnostics", 41.0, "within"),
        ("Northfield Diagnostics", 24.0, "below"),
        ("Harbor Clinical Lab", 19.0, "within"),  # Harbor prints 15-300
    ]
    assert body["results"][0]["band_fraction"] == pytest.approx((64 - 30) / 370, abs=1e-4)


def test_assessment_and_gap_between_labs_are_served(client) -> None:
    body = client.get("/api/v2/labs/2276-4").json()
    assessment = body["assessment"]
    assert assessment["latest_band"] == "within"
    assert assessment["previous_from_other_lab"] is True
    assert assessment["change"] == pytest.approx(-5.0)
    assert assessment["direction"] == "down"
    assert assessment["versus_history"] == "below_prior_range"
    assert body["gap_count"] == 1
    (gap,) = body["gaps"]
    assert (gap["earlier_lab"], gap["later_lab"]) == (
        "Northfield Diagnostics",
        "Harbor Clinical Lab",
    )
    assert (gap["earlier_value"], gap["later_value"]) == (24.0, 19.0)
    assert (gap["earlier_band"], gap["later_band"], gap["bands_disagree"]) == (
        "below",
        "within",
        True,
    )


def test_cross_match_card_reads_one_wearable_stream_before_each_draw(client, observations) -> None:
    body = client.get("/api/v2/labs/2276-4").json()
    match = body["cross_match"]
    assert match["related_metric_id"] == "vital.resting_heart_rate"
    assert match["stream_label"] == "Apple Watch"
    card = match["card"]
    assert card["finding_type"] == "lab_wearable_cross_match"
    assert card["metric"] == "loinc:2276-4"
    # Sep 8 and Sep 17 windows overlap, so three independent draws remain.
    assert card["effect_size"]["kind"] == "cohens_d"
    assert card["confidence"] is None
    assert any("not calibrated confidence" in item for item in card["limitations"])
    assert "from 41 to 19 ng/mL" in card["claim"]
    assert any("counted twice" in item for item in card["limitations"])
    assert card["coverage"]["days_with_data"] == 30
    assert card["sources"][1] == {"source_plugin_id": "apple-healthkit-ios", "label": "Apple Watch"}
    assert {call[0] for call in observations.calls} == {"vital.resting_heart_rate"}
    assert len(observations.calls) == 4  # one bounded window per draw


def test_no_wearable_data_gives_a_reason_not_a_card(client, observations) -> None:
    observations.enabled = False
    match = client.get("/api/v2/labs/718-7").json()["cross_match"]
    assert match["card"] is None
    assert match["reason"].startswith("No heart rate variability (SDNN) data")


def test_unpaired_markers_have_no_cross_match(client) -> None:
    body = client.get("/api/v2/labs/4548-4").json()
    assert body["cross_match"] is None
    assert body["related_metric_id"] is None


def test_route_preserves_unit_uncertainty_in_all_read_models():
    from dataclasses import replace

    row = replace(
        _sample_rows()[0], quality_flags=("unit_unreconciled",), canonical_unit="unverified"
    )
    view = v2_labs._result_view(row)
    assert view.band == "unverified"
    assert view.band_fraction is None
    assert not v2_labs._point(row).interpretable
