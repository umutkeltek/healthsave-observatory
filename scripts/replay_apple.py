"""One-off backfill: re-normalize stored Apple raw payloads into canonical.

Pages through ``raw_ingestion_log`` (source_type=healthsave) and feeds each
stored batch back through the current normalizer via
``replay.orchestrator.replay_apple_raw_payloads`` — the read+write halves of
ADR-0001 Decision H. The canonical insert is idempotent
(``ON CONFLICT DO NOTHING``), so this is safe to re-run and a no-op once
everything is present.

Uses the SAME Apple source_id the live dual-write uses
(``a9b1e7e0-0000-4000-8000-000000000001``) so backfilled observations and future
dual-writes attribute to one Apple source, not two.

Run inside the api container (it has DATABASE_URL + the packages on path)::

    python -m scripts.replay_apple --dry-run --max-pages 1 --limit 50   # verify
    python -m scripts.replay_apple --limit 100                          # full run

``--dry-run`` rolls back every page (normalizes but writes nothing) so you can
confirm the produced/rejected counts before committing anything.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from contracts._base import DEFAULT_OWNER_ID
from replay.orchestrator import replay_apple_raw_payloads
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from storage.timescale.ingest import fetch_raw_payloads
from storage.timescale.observations import CanonicalObservationRepository

# Must match apps/api/server/api/ingest.py::APPLE_HEALTHKIT_SOURCE_ID.
APPLE_HEALTHKIT_SOURCE_ID = uuid.UUID("a9b1e7e0-0000-4000-8000-000000000001")


async def run(*, dry_run: bool, limit: int, max_pages: int | None) -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)
    repo = CanonicalObservationRepository()
    run_id = uuid.uuid4()

    # The orchestrator reads one page; we capture the page's max raw id to
    # advance the ascending-id cursor across the whole table.
    last_id = {"v": 0}

    async def reader(session, *, after_id: int = 0, limit: int = limit):
        rows = await fetch_raw_payloads(session, after_id=after_id, limit=limit)
        if rows:
            last_id["v"] = rows[-1][0]
        return rows

    cursor = 0
    pages = 0
    totals = {"scanned": 0, "produced": 0, "rejected": 0, "submitted": 0}
    mode = "DRY-RUN (rollback)" if dry_run else "COMMIT"
    print(f"replay start: mode={mode} run_id={run_id} limit={limit}", flush=True)

    try:
        while True:
            async with AsyncSession(engine) as session:
                report = await replay_apple_raw_payloads(
                    session,
                    raw_reader=reader,
                    repo=repo,
                    run_id=run_id,
                    source_id=APPLE_HEALTHKIT_SOURCE_ID,
                    owner_id=DEFAULT_OWNER_ID,
                    after_id=cursor,
                    limit=limit,
                )
                if dry_run:
                    await session.rollback()
                else:
                    await session.commit()

            totals["scanned"] += report.payloads_scanned
            totals["produced"] += report.observations_produced
            totals["rejected"] += report.observations_rejected
            totals["submitted"] += report.observations_submitted

            if report.payloads_scanned == 0:
                break
            pages += 1
            cursor = last_id["v"]
            print(
                f"page {pages}: scanned={report.payloads_scanned} "
                f"produced={report.observations_produced} "
                f"rejected={report.observations_rejected} "
                f"submitted={report.observations_submitted} next_cursor={cursor}",
                flush=True,
            )
            if max_pages is not None and pages >= max_pages:
                break
    finally:
        await engine.dispose()

    print(
        f"replay done: mode={mode} pages={pages} "
        f"scanned={totals['scanned']} produced={totals['produced']} "
        f"rejected={totals['rejected']} submitted={totals['submitted']}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill canonical observations from raw Apple payloads."
    )
    ap.add_argument("--dry-run", action="store_true", help="normalize but roll back every page")
    ap.add_argument("--limit", type=int, default=100, help="raw batches per page (default 100)")
    ap.add_argument("--max-pages", type=int, default=None, help="stop after N pages (for a slice)")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit, max_pages=args.max_pages))


if __name__ == "__main__":
    main()
