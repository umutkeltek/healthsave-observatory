"""Import a lab results CSV into HealthSave Observatory (Labs slice 1).

The ``healthsave labs import FILE.csv`` command pipes the file into this module
inside the running ``api`` container, so the file never crosses the network::

    python -m scripts.import_labs [--dry-run] [--name FILE_NAME] PATH|-

The template is documented in ``docs/capture/labs-csv.md``. The whole file is
validated first; if any row is invalid, nothing is written.

Exit codes:
  0   imported (or the dry run passed)
  2   usage error (bad arguments, unreadable path)
  65  the file was rejected (deterministic, the 422 class): nothing was
      written, and running it again unchanged gives the same answer
  75  the database could not be reached (transient): safe to retry
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from contracts._base import DEFAULT_OWNER_ID
from normalization.labs import (
    FLAG_UNIT_UNRECONCILED,
    LABS_CSV_PLUGIN,
    LabCsvParse,
    LabCsvValidationError,
    NormalizedLabResult,
    parse_lab_csv,
)
from storage.timescale.labs import (
    LabImportSummary,
    LabResultWrite,
    default_repository,
    is_transient_db_error,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REJECTED = 65  # sysexits EX_DATAERR
EXIT_TEMPFAIL = 75  # sysexits EX_TEMPFAIL

_WRITE_FIELDS = tuple(f.name for f in fields(LabResultWrite))


def to_write(result: NormalizedLabResult) -> LabResultWrite:
    """Normalized result → storage write record (same fields, by name)."""
    return LabResultWrite(**{name: getattr(result, name) for name in _WRITE_FIELDS})


def describe(parsed: LabCsvParse) -> str:
    results = parsed.results
    labs = sorted({r.lab_name for r in results})
    markers = sorted({r.loinc_code for r in results})
    first = min(r.specimen_at for r in results).date().isoformat()
    last = max(r.specimen_at for r in results).date().isoformat()
    span = first if first == last else f"{first} to {last}"
    return (
        f"{len(results)} result(s) for {len(markers)} marker(s) from {len(labs)} lab(s) "
        f"({', '.join(labs)}), {span}"
    )


def _notes(parsed: LabCsvParse) -> list[str]:
    notes = []
    if parsed.duplicates_collapsed:
        notes.append(f"{parsed.duplicates_collapsed} identical duplicate row(s) were counted once.")
    unreconciled = sorted(
        {r.canonical_unit for r in parsed.results if FLAG_UNIT_UNRECONCILED in r.quality_flags}
    )
    if unreconciled:
        notes.append(
            "Kept as written, not converted (unit not in the table): " + ", ".join(unreconciled)
        )
    return notes


def _default_session_factory() -> Callable[[], Any]:
    # Imported lazily: the API package wires the engine from DATABASE_URL.
    from server.db.session import async_session

    return async_session


async def _write(parsed: LabCsvParse, session_factory: Callable[[], Any]) -> LabImportSummary:
    async with session_factory() as session:
        summary = await default_repository.import_results(
            session,
            [to_write(result) for result in parsed.results],
            plugin_id=LABS_CSV_PLUGIN,
            owner_id=DEFAULT_OWNER_ID,
        )
        await session.commit()
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="healthsave labs import",
        description="Import blood test results from a CSV file (docs/capture/labs-csv.md).",
    )
    parser.add_argument("path", help="CSV file, or - to read standard input")
    parser.add_argument("--dry-run", action="store_true", help="validate only; write nothing")
    parser.add_argument("--name", help="file name to record (when reading standard input)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
    now: datetime | None = None,
    stdin: IO[bytes] | None = None,
    out: IO[str] | None = None,
    err: IO[str] | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        args = build_arg_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK

    if args.path == "-":
        data = (stdin or sys.stdin.buffer).read()
        file_name = args.name or "stdin.csv"
    else:
        path = Path(args.path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            print(f"Cannot read {path}: {exc.strerror or exc}", file=err)
            return EXIT_USAGE
        file_name = args.name or path.name

    try:
        parsed = parse_lab_csv(
            data,
            owner_id=DEFAULT_OWNER_ID,
            now=now or datetime.now(UTC),
            file_name=file_name,
        )
    except LabCsvValidationError as exc:
        print(
            f"{file_name} was rejected; nothing was written. "
            f"Fix {len(exc.errors)} problem(s) and run it again:",
            file=err,
        )
        for problem in exc.errors:
            print(f"  {problem}", file=err)
        return EXIT_REJECTED

    if args.dry_run:
        print(f"Dry run, nothing written. {file_name}: {describe(parsed)}.", file=out)
        for note in _notes(parsed):
            print(note, file=out)
        return EXIT_OK

    try:
        summary = asyncio.run(_write(parsed, session_factory or _default_session_factory()))
    except Exception as exc:
        if is_transient_db_error(exc):
            print(
                f"Could not reach the database ({type(exc).__name__}); nothing was written. "
                "Check that the stack is up (healthsave status) and run it again.",
                file=err,
            )
            return EXIT_TEMPFAIL
        raise

    print(
        f"Imported {file_name}: {describe(parsed)}. "
        f"{summary.inserted} new, {summary.updated} updated, {summary.unchanged} unchanged.",
        file=out,
    )
    for note in _notes(parsed):
        print(note, file=out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
