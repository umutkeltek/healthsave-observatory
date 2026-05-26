"""Grafana dashboards should query the public datahub schema, not legacy private tables."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARDS = ROOT / "deploy" / "grafana" / "dashboards"


def _raw_sql() -> list[tuple[str, str]]:
    queries: list[tuple[str, str]] = []

    def walk(file_name: str, node) -> None:
        if isinstance(node, dict):
            raw = node.get("rawSql")
            if isinstance(raw, str):
                queries.append((file_name, raw))
            for value in node.values():
                walk(file_name, value)
        elif isinstance(node, list):
            for value in node:
                walk(file_name, value)

    for path in sorted(DASHBOARDS.glob("*.json")):
        walk(path.name, json.loads(path.read_text()))
    return queries


def _dashboard(file_name: str) -> dict:
    return json.loads((DASHBOARDS / file_name).read_text())


def _panel_sql(file_name: str, title: str) -> str:
    dashboard = _dashboard(file_name)
    for panel in dashboard["panels"]:
        if panel.get("title") == title:
            targets = panel.get("targets", [])
            return "\n".join(target.get("rawSql", "") for target in targets)
    raise AssertionError(f"panel not found: {file_name} / {title}")


def test_dashboards_do_not_query_legacy_personal_stack_columns():
    forbidden = (
        "sleep_efficiency_pct",
        "sleep_performance_pct",
        "ss.is_nap",
        "daily_activity\nWHERE $__timeFilter(date) AND device_id IN ($device) AND strain",
        "Owner''s Apple Watch",
    )

    offenders = [
        (file_name, term, sql) for file_name, sql in _raw_sql() for term in forbidden if term in sql
    ]

    assert offenders == []


def test_heart_rate_dashboard_uses_bpm_column_not_legacy_value_column():
    offenders = [
        (file_name, sql)
        for file_name, sql in _raw_sql()
        if "FROM heart_rate" in sql and "avg(value)" in sql
    ]

    assert offenders == []


def test_grafana_service_receives_db_password_for_datasource_provisioning():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    grafana_env = compose["services"]["grafana"]["environment"]

    assert grafana_env["DB_PASSWORD"] == "${DB_PASSWORD:-changeme}"


def test_whoop_dashboards_use_the_normalized_public_metric_paths():
    """Whoop plugin output is normalized into quantity_samples plus
    dedicated HRV / SpO2 / temperature tables, not the legacy-style
    recovery table used by the private personal stack.
    """
    insights_queries = [sql for file_name, sql in _raw_sql() if file_name == "insights.json"]

    assert all(
        "FROM recovery" not in sql and "JOIN recovery" not in sql for sql in insights_queries
    )


def test_whoop_dashboard_metric_coverage_matches_plugin_output():
    raw = "\n".join(sql for _, sql in _raw_sql())

    for metric_name in (
        "recovery_score",
        "resting_heart_rate",
        "strain",
        "sleep_duration_hours",
        "sleep_efficiency_percentage",
        "sleep_respiratory_rate",
    ):
        assert metric_name in raw


def test_sleep_duration_dashboard_uses_single_best_source_per_day():
    sql = _panel_sql("sleep.json", "Sleep Duration Trend")

    assert "FROM sleep_sessions" in sql
    assert "row_number() OVER (PARTITION BY time" in sql
    assert "LEAST(hours, 16)" in sql
    assert "FROM sleep_stages" not in sql


def test_sleep_stat_cards_do_not_sum_overlapping_stage_sources():
    panels = (
        "Avg Sleep Duration (7d)",
        "Avg Deep Sleep (7d)",
        "Avg REM Sleep (7d)",
        "Sleep Efficiency (7d)",
    )

    for title in panels:
        sql = _panel_sql("sleep.json", title)
        assert "FROM sleep_sessions" in sql
        assert "row_number() OVER (PARTITION BY day" in sql
        assert "FROM sleep_stages" not in sql


def test_overview_sleep_duration_uses_single_best_source_per_day():
    sql = _panel_sql("healthsave-overview.json", "Sleep Duration (14 Days)")

    assert "FROM sleep_sessions" in sql
    assert "row_number() OVER (PARTITION BY time" in sql
    assert "LEAST(hours, 16)" in sql
    assert "FROM sleep_stages" not in sql


def test_overview_latest_hr_stat_does_not_show_stale_all_time_value():
    sql = _panel_sql("healthsave-overview.json", "Latest HR")

    assert "FROM heart_rate" in sql
    assert "time >= now() - interval '24 hours'" in sql
    assert "COALESCE" not in sql
