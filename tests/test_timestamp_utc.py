"""DATA-001: timestamps written to TIMESTAMPTZ columns must be tz-aware.

The wire contract is ISO 8601 with a trailing Z (UTC). An offset-less value is
assumed UTC and never stored naive. These guard both writers -- the v1
projection parser and the canonical normalizer parser. The fix is a no-op for
the normal Z path, so the live iOS contract is unaffected.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.apple import _parse_ts  # noqa: E402
from server.ingestion.parsers import parse_ts  # noqa: E402


def test_parse_ts_z_suffix_is_utc_aware():
    parsed = parse_ts("2026-04-10T12:00:00Z")
    assert parsed == datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)
    assert parsed.tzinfo is not None


def test_parse_ts_naive_input_assumed_utc():
    parsed = parse_ts("2026-04-10T12:00:00")
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)


def test_parse_ts_preserves_explicit_offset():
    parsed = parse_ts("2026-04-10T12:00:00+02:00")
    assert parsed.utcoffset().total_seconds() == 2 * 3600


def test_parse_ts_invalid_returns_none():
    assert parse_ts("not-a-timestamp") is None
    assert parse_ts(None) is None
    assert parse_ts("") is None


def test_canonical_parse_ts_naive_input_assumed_utc():
    parsed = _parse_ts("2026-04-10T12:00:00")
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)


def test_canonical_parse_ts_z_suffix_is_utc_aware():
    parsed = _parse_ts("2026-04-10T12:00:00Z")
    assert parsed == datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)
