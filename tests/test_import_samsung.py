"""Tests for ``scripts/import_samsung.py``."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import import_samsung  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "samsung"


def _by_metric(samples, metric: str):
    return [s for s in samples if s.metric == metric]


# ─── parse_date + extract_source ─────────────────────────────────────


def test_parse_date_accepts_samsung_dotted_format():
    dt = import_samsung.parse_date("2019.11.29 00.50")
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2019, 11, 29, 0, 50)


def test_parse_date_accepts_huawei_colon_seconds_format():
    dt = import_samsung.parse_date("2024.12.30 05:43:00")
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (
        2024,
        12,
        30,
        5,
        43,
        0,
    )


def test_parse_date_returns_none_on_garbage():
    assert import_samsung.parse_date("") is None
    assert import_samsung.parse_date("not a date") is None


def test_extract_source_finds_samsung_or_huawei_or_unknown():
    assert import_samsung.extract_source("Steps 2024.01.03 Samsung Health.csv") == "Samsung Health"
    assert import_samsung.extract_source("Sleep 1-2024 Huawei Health.csv") == "Huawei Health"
    assert import_samsung.extract_source("mystery_export.csv") == "Unknown"


# ─── per-category parsers ────────────────────────────────────────────


def test_parse_steps_csv_skips_zero_and_invalid_rows():
    text = (
        FIXTURES / "Health Sync Steps" / "Steps 2024.01.03 00.00 Samsung Health.csv"
    ).read_text()
    samples = list(import_samsung.parse_steps_csv(io.StringIO(text), source="Samsung Health"))
    # 4 rows; one is 0 steps -> skipped.
    assert len(samples) == 3
    assert all(s.metric == "step_count" for s in samples)
    assert [s.payload["qty"] for s in samples] == [42, 118, 73]
    assert samples[0].payload["source"] == "Samsung Health"
    assert samples[0].payload["date"].endswith("Z")


def test_parse_heart_rate_csv_rejects_out_of_range_bpm():
    text = (
        FIXTURES / "Health Sync Heart rate" / "Heart rate 2024.01.03 00.00 Samsung Health.csv"
    ).read_text()
    samples = list(import_samsung.parse_heart_rate_csv(io.StringIO(text), source="Samsung Health"))
    # 4 rows: 72, 84, 300 (>250 reject), 0 (<=0 reject) -> 2 surviving.
    assert len(samples) == 2
    assert [s.payload["qty"] for s in samples] == [72, 84]
    assert all(s.payload["context"] == "continuous" for s in samples)


def test_parse_sleep_csv_yields_start_end_value_source():
    text = (FIXTURES / "Health Sync Sleep" / "Sleep 1-2024 Huawei Health.csv").read_text()
    samples = list(import_samsung.parse_sleep_csv(io.StringIO(text), source="Huawei Health"))
    # 3 rows; one has 0 duration -> skipped.
    assert len(samples) == 2
    payload = samples[0].payload
    for key in ("start", "end", "value", "source"):
        assert key in payload
    # start at 00:30, +1800s -> 01:00.
    assert payload["start"] == "2024-01-03T00:30:00Z"
    assert payload["end"] == "2024-01-03T01:00:00Z"
    assert payload["value"] == "light"


def test_parse_weight_csv_emits_both_mass_and_body_fat_when_present():
    text = (FIXTURES / "Health Sync Weight" / "Weight 2024.01.03 Samsung Health.csv").read_text()
    samples = list(import_samsung.parse_weight_csv(io.StringIO(text), source="Samsung Health"))
    body_mass = _by_metric(samples, "body_mass")
    body_fat = _by_metric(samples, "body_fat_percentage")
    # row 1: weight + bf -> 2 samples. row 2: weight only -> 1. row 3: zero -> 0.
    assert [s.payload["qty"] for s in body_mass] == [78.2, 78.1]
    assert [s.payload["qty"] for s in body_fat] == [21.4]
    assert all(s.payload["unit"] == "kg" for s in body_mass)


def test_parse_spo2_csv_rejects_out_of_range_values():
    text = (
        FIXTURES
        / "Health Sync Oxygen saturation"
        / "Oxygen saturation 2024.01.03 Samsung Health.csv"
    ).read_text()
    samples = list(import_samsung.parse_spo2_csv(io.StringIO(text), source="Samsung Health"))
    # 4 rows: 97, 98, 0 (reject), 150 (reject) -> 2 surviving.
    assert len(samples) == 2
    assert [s.payload["qty"] for s in samples] == [97.0, 98.0]
    assert all(s.payload["context"] == "overnight" for s in samples)


# ─── walk_directory + batching ────────────────────────────────────────


def test_walk_directory_reads_all_subdirs():
    result = import_samsung.walk_directory(FIXTURES)
    metrics = {s.metric for s in result.samples}
    assert metrics == {
        "step_count",
        "heart_rate",
        "sleep_analysis",
        "body_mass",
        "body_fat_percentage",
        "oxygen_saturation",
    }


def test_walk_directory_raises_when_root_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        import_samsung.walk_directory(tmp_path / "nope")


def test_batches_for_groups_by_metric_and_chunks():
    samples = [
        import_samsung.Sample("heart_rate", {"date": "x", "qty": i, "source": "S"})
        for i in range(0, 5)
    ] + [
        import_samsung.Sample("step_count", {"date": "x", "qty": i, "source": "S"})
        for i in range(0, 3)
    ]
    out = list(import_samsung.batches_for(samples, batch_size=2))
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for batch in out:
        by_metric.setdefault(batch["metric"], []).append(batch)
    assert len(by_metric["heart_rate"]) == 3  # 2,2,1
    assert len(by_metric["step_count"]) == 2  # 2,1
    # total_batches consistent within a metric
    assert {b["total_batches"] for b in by_metric["heart_rate"]} == {3}
    assert {b["total_batches"] for b in by_metric["step_count"]} == {2}


def test_batches_for_emits_empty_batch_when_no_samples():
    out = list(import_samsung.batches_for([], batch_size=10))
    assert out == []


def test_post_batches_uses_api_key_header_and_path():
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": request.content,
            }
        )
        return httpx.Response(200, json={"status": "processed"})

    transport = httpx.MockTransport(handler)
    batches = [
        {
            "metric": "step_count",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [{"date": "x", "qty": 1}],
        }
    ]
    sent_batches, sent_records = import_samsung.post_batches(
        batches,
        base_url="http://hub.example",
        api_key="K",
        transport=transport,
    )
    assert sent_batches == 1
    assert sent_records == 1
    assert captured[0]["url"].endswith("/api/apple/batch")
    assert captured[0]["headers"].get("x-api-key") == "K"


def test_post_batches_raises_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        import_samsung.post_batches(
            [
                {
                    "metric": "step_count",
                    "batch_index": 0,
                    "total_batches": 1,
                    "samples": [],
                }
            ],
            base_url="http://hub.example",
            transport=transport,
        )


def test_main_dry_run_does_not_post(capsys):
    rc = import_samsung.main([str(FIXTURES), "--dry-run"])
    assert rc == 0
