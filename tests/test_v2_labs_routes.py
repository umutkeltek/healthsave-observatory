"""v2 Labs read endpoints (no database; the lab repository is faked).

Rows come from the synthetic sample CSV run through the real normalizer, so the
routes are exercised on the same shapes an import writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import server
from fastapi.testclient import TestClient
from normalization.labs import parse_lab_csv
from server.api import deps, v2_labs
from server.api.deps import get_session
from storage.timescale.labs import LabResultRow

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


@pytest.fixture
def repo(monkeypatch):
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
