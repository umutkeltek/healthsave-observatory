"""`python -m scripts.import_labs` — exit codes, dry run, and the write path."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import import_labs

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "labs" / "sample_labs.csv"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class _Result:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self):
        self.statements: list[str] = []
        self.committed = False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        if sql.startswith("INSERT INTO lab_results"):
            return _Result(SimpleNamespace(inserted=True))
        return _Result()

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _run(argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = import_labs.main(argv, now=NOW, out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def _never_called():
    raise AssertionError("the database must not be touched")


def test_dry_run_validates_and_writes_nothing() -> None:
    code, out, err = _run([str(SAMPLE), "--dry-run"], session_factory=_never_called)
    assert code == import_labs.EXIT_OK, err
    assert out.startswith("Dry run, nothing written. sample_labs.csv: 12 result(s)")
    assert "4 marker(s) from 2 lab(s)" in out
    assert "2025-11-18 to 2026-09-17" in out


def test_import_writes_every_row_in_one_committed_session() -> None:
    session = _Session()
    code, out, err = _run([str(SAMPLE)], session_factory=lambda: session)
    assert code == import_labs.EXIT_OK, err
    assert session.committed
    assert sum(s.startswith("INSERT INTO lab_results") for s in session.statements) == 12
    assert "12 new, 0 updated, 0 unchanged." in out


def test_rejected_file_exits_65_lists_rows_and_never_touches_the_database(tmp_path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "specimen_datetime,loinc,value,unit,lab\n"
        "2026-01-02,2276-5,40,ng/mL,Lab A\n"
        "2026-01-02,718-7,x,g/dL,Lab A\n"
    )
    code, out, err = _run([str(bad)], session_factory=_never_called)
    assert code == import_labs.EXIT_REJECTED == 65
    assert "bad.csv was rejected; nothing was written. Fix 2 problem(s)" in err
    assert "row 2, column loinc" in err
    assert "row 3, column value" in err
    assert out == ""


def test_unreachable_database_exits_75_as_retryable() -> None:
    def refuse():
        raise ConnectionRefusedError("connection refused")

    code, _, err = _run([str(SAMPLE)], session_factory=refuse)
    assert code == import_labs.EXIT_TEMPFAIL == 75
    assert "Could not reach the database" in err


def test_unexpected_write_failures_are_not_reported_as_transient() -> None:
    def broken():
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        _run([str(SAMPLE)], session_factory=broken)


def test_stdin_import_records_the_given_file_name() -> None:
    session = _Session()
    code, out, err = _run(
        ["-", "--name", "march.csv"],
        session_factory=lambda: session,
        stdin=io.BytesIO(SAMPLE.read_bytes()),
    )
    assert code == import_labs.EXIT_OK, err
    assert out.startswith("Imported march.csv:")


def test_missing_file_and_bad_arguments_are_usage_errors(tmp_path) -> None:
    code, _, err = _run([str(tmp_path / "nope.csv")], session_factory=_never_called)
    assert code == import_labs.EXIT_USAGE
    assert "Cannot read" in err
    assert _run([], session_factory=_never_called)[0] == import_labs.EXIT_USAGE
