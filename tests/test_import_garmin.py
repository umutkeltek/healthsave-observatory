"""Tests for ``scripts/import_garmin.py``."""

from __future__ import annotations

import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import import_garmin  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"


def _samples_for(metric: str, samples):
    return [s for s in samples if s.metric == metric]


def test_parse_tcx_yields_heart_rate_samples_with_iso_timestamps():
    text = (FIXTURES / "sample.tcx").read_text(encoding="utf-8")
    samples = list(import_garmin.parse_tcx(text, source="Garmin"))

    assert len(samples) == 6
    assert all(s.metric == "heart_rate" for s in samples)
    first = samples[0].payload
    assert first["date"] == "2026-04-10T07:00:00Z"
    assert first["qty"] == 78
    assert first["unit"] == "count/min"
    assert first["source"] == "Garmin"
    assert [s.payload["qty"] for s in samples] == [78, 92, 118, 134, 141, 146]


def test_parse_steps_json_yields_one_sample_per_day():
    obj = json.loads((FIXTURES / "sample_steps.json").read_text())
    samples = list(import_garmin.parse_steps_json(obj))

    assert len(samples) == 7
    assert all(s.metric == "step_count" for s in samples)
    first = samples[0].payload
    assert first["date"] == "2026-04-04T00:00:00Z"
    assert first["qty"] == 8421
    assert first["unit"] == "count"
    assert first["source"] == "Garmin"


def test_parse_sleep_json_maps_activity_levels_to_canonical_stages():
    obj = json.loads((FIXTURES / "sample_sleep.json").read_text())
    samples = list(import_garmin.parse_sleep_json(obj))

    assert len(samples) == 8
    assert all(s.metric == "sleep_analysis" for s in samples)
    stages = [s.payload["value"] for s in samples]
    assert stages == ["light", "deep", "light", "rem", "deep", "light", "awake", "light"]

    first = samples[0].payload
    assert first["start_date"] == "2026-04-09T22:00:00Z"
    assert first["end_date"] == "2026-04-09T22:45:00Z"
    assert first["source"] == "Garmin"


def test_parse_sleep_json_skips_unknown_activity_level():
    obj = {
        "sleepLevels": [
            {
                "startGMT": "2026-04-10T00:00:00Z",
                "endGMT": "2026-04-10T01:00:00Z",
                "activityLevel": 99,
            }
        ]
    }
    assert list(import_garmin.parse_sleep_json(obj)) == []


def test_parse_fit_translates_record_messages_to_heart_rate_samples():
    """FIT parsing is exercised via a mock FitFile to avoid bundling a binary fixture."""

    class FakeField:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class FakeRecord:
        def __init__(self, fields):
            self._fields = fields

        def __iter__(self):
            return iter(self._fields)

    class FakeFitFile:
        def __init__(self, _stream):
            pass

        def get_messages(self, name):
            assert name == "record"
            return [
                FakeRecord(
                    [
                        FakeField("timestamp", datetime(2026, 4, 10, 7, 0, 0, tzinfo=UTC)),
                        FakeField("heart_rate", 110),
                    ]
                ),
                # Records without heart_rate are skipped.
                FakeRecord([FakeField("timestamp", datetime(2026, 4, 10, 7, 0, 1, tzinfo=UTC))]),
                FakeRecord(
                    [
                        FakeField("timestamp", datetime(2026, 4, 10, 7, 0, 2, tzinfo=UTC)),
                        FakeField("heart_rate", 115),
                    ]
                ),
            ]

    with patch.dict("sys.modules", {"fitparse": type("M", (), {"FitFile": FakeFitFile})()}):
        samples = list(import_garmin.parse_fit(io.BytesIO(b""), source="Garmin Forerunner"))

    assert [s.payload["qty"] for s in samples] == [110, 115]
    assert samples[0].payload["date"] == "2026-04-10T07:00:00Z"
    assert samples[0].payload["source"] == "Garmin Forerunner"


def test_build_batches_groups_by_metric_and_chunks():
    samples = [
        import_garmin.Sample("heart_rate", {"date": "2026-04-10T00:00:00Z", "qty": 70}),
        import_garmin.Sample("heart_rate", {"date": "2026-04-10T00:00:01Z", "qty": 71}),
        import_garmin.Sample("heart_rate", {"date": "2026-04-10T00:00:02Z", "qty": 72}),
        import_garmin.Sample("step_count", {"date": "2026-04-10T00:00:00Z", "qty": 9000}),
    ]
    batches = list(import_garmin.build_batches(samples, batch_size=2))

    by_metric = {}
    for batch in batches:
        by_metric.setdefault(batch["metric"], []).append(batch)

    hr_batches = by_metric["heart_rate"]
    assert len(hr_batches) == 2
    assert hr_batches[0]["batch_index"] == 0
    assert hr_batches[0]["total_batches"] == 2
    assert len(hr_batches[0]["samples"]) == 2
    assert len(hr_batches[1]["samples"]) == 1

    steps_batches = by_metric["step_count"]
    assert len(steps_batches) == 1
    assert steps_batches[0]["total_batches"] == 1


def test_post_batches_sends_correct_payload_and_headers_with_mock_transport():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "headers": {k: v for k, v in request.headers.items()},
                "body": json.loads(request.content.decode()),
            }
        )
        return httpx.Response(200, json={"status": "processed", "records": 1})

    transport = httpx.MockTransport(handler)
    batches = [
        {
            "metric": "heart_rate",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [{"date": "2026-04-10T00:00:00Z", "qty": 70}],
        }
    ]

    sent_batches, sent_records = import_garmin.post_batches(
        batches,
        base_url="http://hub.example",
        api_key="secret-key",
        transport=transport,
    )

    assert sent_batches == 1
    assert sent_records == 1
    assert captured[0]["url"] == "http://hub.example/api/apple/batch"
    assert captured[0]["headers"]["x-api-key"] == "secret-key"
    assert captured[0]["body"]["metric"] == "heart_rate"


def test_main_dry_run_writes_batches_to_stdout(tmp_path):
    out = io.StringIO()
    exit_code = import_garmin.main(
        argv=[
            "--tcx",
            str(FIXTURES / "sample.tcx"),
            "--steps-json",
            str(FIXTURES / "sample_steps.json"),
            "--dry-run",
        ],
        out=out,
    )
    assert exit_code == 0

    payload = json.loads(out.getvalue())
    metrics = sorted({batch["metric"] for batch in payload})
    assert metrics == ["heart_rate", "step_count"]
    total_records = sum(len(batch["samples"]) for batch in payload)
    assert total_records == 6 + 7  # tcx trackpoints + step days


def test_main_requires_at_least_one_input(capsys):
    exit_code = import_garmin.main(argv=["--server", "http://example"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "input flag is required" in err


def test_main_calls_poster_when_not_dry_run():
    calls = []

    def fake_poster(batches, *, base_url, api_key):
        batches = list(batches)
        calls.append({"count": len(batches), "base_url": base_url, "api_key": api_key})
        return len(batches), sum(len(b["samples"]) for b in batches)

    exit_code = import_garmin.main(
        argv=[
            "--steps-json",
            str(FIXTURES / "sample_steps.json"),
            "--server",
            "http://hub.example",
            "--api-key",
            "k",
        ],
        poster=fake_poster,
    )

    assert exit_code == 0
    assert calls == [{"count": 1, "base_url": "http://hub.example", "api_key": "k"}]


def test_parse_zip_dispatches_per_file_extension(tmp_path):
    import zipfile

    zip_path = tmp_path / "garmin.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("DI_CONNECT/DI-Connect-Fitness/run.tcx", (FIXTURES / "sample.tcx").read_text())
        zf.writestr(
            "DI_CONNECT/DI-Connect-Wellness/UDS_steps_2026.json",
            (FIXTURES / "sample_steps.json").read_text(),
        )
        zf.writestr(
            "DI_CONNECT/DI-Connect-Wellness/sleepData_2026.json",
            (FIXTURES / "sample_sleep.json").read_text(),
        )

    samples = list(import_garmin.parse_zip(zip_path))

    metrics = {s.metric for s in samples}
    assert metrics == {"heart_rate", "step_count", "sleep_analysis"}
    assert len(_samples_for("heart_rate", samples)) == 6
    assert len(_samples_for("step_count", samples)) == 7
    assert len(_samples_for("sleep_analysis", samples)) == 8


def test_sleep_samples_round_trip_through_existing_sleep_aggregator():
    """Ensure the shape we emit is what ``server.ingestion.sleep`` consumes."""
    from server.ingestion.sleep import sleep_session_rows

    obj = json.loads((FIXTURES / "sample_sleep.json").read_text())
    samples = [s.payload for s in import_garmin.parse_sleep_json(obj)]
    sessions = sleep_session_rows(device_id=1, samples=samples)

    # One night -> one session row with non-zero deep/rem/light durations.
    assert len(sessions) == 1
    assert sessions[0]["deep"] > 0
    assert sessions[0]["rem"] > 0
    assert sessions[0]["light"] > 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-10T07:00:00Z", "2026-04-10T07:00:00Z"),
        ("2026-04-10T07:00:00+00:00", "2026-04-10T07:00:00Z"),
        ("1776384000000", "2026-04-17T00:00:00Z"),
    ],
)
def test_normalise_iso_handles_common_formats(raw, expected):
    assert import_garmin._normalise_iso(raw) == expected
