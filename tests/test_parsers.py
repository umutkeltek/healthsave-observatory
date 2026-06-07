"""Parser hardening for poison numeric inputs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.ingestion.parsers import to_float, to_int  # noqa: E402


def test_to_float_returns_none_for_overflowing_integer() -> None:
    assert to_float(10**400) is None


def test_to_float_returns_none_for_non_finite_strings() -> None:
    assert to_float("nan") is None
    assert to_float("inf") is None
    assert to_float("-inf") is None


def test_to_float_returns_none_for_non_finite_floats() -> None:
    assert to_float(float("inf")) is None
    assert to_float(float("nan")) is None


def test_to_int_returns_none_for_non_finite_and_overflowing_inputs() -> None:
    assert to_int(float("inf")) is None
    assert to_int(float("nan")) is None
    assert to_int("nan") is None
    assert to_int(10**400) is None


def test_parser_normal_values_are_unchanged() -> None:
    assert to_float("72.5") == 72.5
    assert to_float(72) == 72.0
    assert to_int("72") == 72
    assert to_int(72.9) == 72
    assert to_float(None) is None
    assert to_int(None) is None
    assert to_float("not a number") is None
