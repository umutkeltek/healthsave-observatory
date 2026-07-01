from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from storage.timescale.sync_readiness import build_decision_readiness, known_contract_metrics


def _coverage_row(**overrides):
    row = {
        "metric": "step_count",
        "batches_seen": 1,
        "batches_processed": 1,
        "batches_empty": 0,
        "batches_failed": 0,
        "records_received": 12,
        "records_accepted": 12,
        "records_inserted_new": 12,
        "records_deduped_existing": 0,
        "storage_result_level": "inserted_vs_existing",
        "records_skipped": 0,
        "newest_receipt_at": datetime(2026, 7, 1, 19, 18, tzinfo=UTC),
        "receipt_sample_window": {
            "min_sample_time": datetime(2026, 7, 1, 19, 0, tzinfo=UTC),
            "max_sample_time": datetime(2026, 7, 1, 19, 17, tzinfo=UTC),
        },
        "destination_row_count": 1,
        "latest_destination_sample_time": datetime(2026, 7, 1, 19, 17, tzinfo=UTC),
        "freshness_state": "fresh",
    }
    row.update(overrides)
    return row


def test_readiness_marks_recent_materialized_daily_metric_ready() -> None:
    now = datetime(2026, 7, 1, 19, 30, tzinfo=UTC)

    result = build_decision_readiness([_coverage_row()], now=now, known_metrics=("step_count",))
    row = result["per_metric"][0]

    assert row["metric"] == "step_count"
    assert row["window_key"] == "today_local"
    assert row["ready"] is True
    assert row["status"] == "ready"
    assert row["freshness_seconds"] == 12 * 60
    assert row["observed_at"] == datetime(2026, 7, 1, 19, 18, tzinfo=UTC)
    assert row["materialized_at"] == datetime(2026, 7, 1, 19, 17, tzinfo=UTC)


def test_readiness_uses_receipt_freshness_for_materialized_daily_rollups() -> None:
    now = datetime(2026, 7, 1, 17, 55, tzinfo=UTC)
    local_midnight_utc = datetime(2026, 6, 30, 21, tzinfo=UTC)

    result = build_decision_readiness(
        [
            _coverage_row(
                newest_receipt_at=now - timedelta(minutes=5),
                receipt_sample_window={
                    "min_sample_time": datetime(2017, 3, 4, 21, tzinfo=UTC),
                    "max_sample_time": local_midnight_utc,
                },
                latest_destination_sample_time=local_midnight_utc,
                freshness_state="fresh",
            )
        ],
        now=now,
        known_metrics=("step_count",),
    )

    row = result["per_metric"][0]

    assert row["ready"] is True
    assert row["status"] == "ready"
    assert row["freshness_seconds"] == 5 * 60
    assert row["observed_at"] == now - timedelta(minutes=5)
    assert row["materialized_at"] == local_midnight_utc


def test_readiness_does_not_treat_recent_receipt_as_materialized_steps() -> None:
    now = datetime(2026, 7, 1, 19, 30, tzinfo=UTC)

    result = build_decision_readiness(
        [
            _coverage_row(
                destination_row_count=0,
                latest_destination_sample_time=None,
                freshness_state="receipt_only",
            )
        ],
        now=now,
        known_metrics=("step_count",),
    )
    row = result["per_metric"][0]

    assert row["ready"] is False
    assert row["status"] == "receipt_only"
    assert row["receipt_at"] == datetime(2026, 7, 1, 19, 18, tzinfo=UTC)
    assert row["materialized_at"] is None


def test_readiness_marks_old_latest_sample_stale_even_with_fresh_coverage_state() -> None:
    now = datetime(2026, 7, 1, 19, 30, tzinfo=UTC)
    old_sample = now - timedelta(hours=7)

    result = build_decision_readiness(
        [
            _coverage_row(
                metric="heart_rate",
                newest_receipt_at=now - timedelta(minutes=5),
                receipt_sample_window={
                    "min_sample_time": old_sample,
                    "max_sample_time": old_sample,
                },
                latest_destination_sample_time=old_sample,
                freshness_state="fresh",
            )
        ],
        now=now,
        known_metrics=("heart_rate",),
    )
    row = result["per_metric"][0]

    assert row["ready"] is False
    assert row["status"] == "stale"
    assert row["freshness_seconds"] == 7 * 60 * 60


def test_readiness_returns_missing_rows_for_known_unobserved_metrics() -> None:
    now = datetime(2026, 7, 1, 19, 30, tzinfo=UTC)

    result = build_decision_readiness([], now=now, known_metrics=("body_mass", "step_count"))
    rows = {row["metric"]: row for row in result["per_metric"]}

    assert rows["body_mass"]["status"] == "missing"
    assert rows["body_mass"]["ready"] is False
    assert rows["step_count"]["window_key"] == "today_local"


def test_known_contract_metrics_loads_source_manifest(monkeypatch) -> None:
    monkeypatch.delenv("HEALTHSAVE_PARITY_MANIFEST", raising=False)
    known_contract_metrics.cache_clear()

    try:
        metrics = known_contract_metrics()
    finally:
        known_contract_metrics.cache_clear()

    assert "step_count" in metrics
    assert "body_mass" in metrics


def test_known_contract_metrics_supports_runtime_manifest_override(monkeypatch, tmp_path) -> None:
    manifest = tmp_path / "parity.json"
    manifest.write_text(
        json.dumps({"metrics": {"step_count": {}, "body_mass": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HEALTHSAVE_PARITY_MANIFEST", str(manifest))
    known_contract_metrics.cache_clear()

    try:
        metrics = known_contract_metrics()
    finally:
        known_contract_metrics.cache_clear()

    assert metrics == ("body_mass", "step_count")


def test_docker_image_copies_parity_manifest_for_readiness_runtime() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"

    assert "COPY contracts/parity.json ./contracts/parity.json" in dockerfile.read_text(
        encoding="utf-8"
    )
