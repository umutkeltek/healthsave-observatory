"""Back-fill ONE metric's stored raw batches into shown readings.

For a metric the server stored raw but could not show: before 1.5.2,
``heart_rate_variability_rmssd`` (iPhone on iOS 27, Android) landed in
``quantity_samples`` but had no canonical metric, so the web, the metric list
and the AI connector never saw it. Once the metric exists (``vital.hrv_rmssd``),
this replays the stored raw batches of that one metric through the current
normalizer with ``replay.orchestrator.backfill_metric_from_raw``.

Safe by construction:

* add-only: the live dual-write's own insert, which only replaces a row from
  an OLDER raw batch; a replayed row carries the same raw batch id as any row
  already there, so nothing present is rewritten and a second run adds nothing;
* one metric only: observations of any other metric are dropped, and the
  batches' own deletions are replayed scoped to this metric, in stored order;
* the owner comes from each batch's sync receipt; a batch without one goes to
  the default owner only on a single-person Observatory, otherwise it is
  skipped and counted;
* every page is checked inside its own transaction: if this run wrote a row of
  any other metric, the page is rolled back and the run stops (exit non-zero).

Run inside the api container (DATABASE_URL + packages on path)::

    python -m scripts.backfill_metric --metric heart_rate_variability_rmssd --dry-run
    python -m scripts.backfill_metric --metric heart_rate_variability_rmssd

``--dry-run`` normalizes every page and rolls it back, so the printed counts
show what a real run would add before anything is written.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from contracts._base import DEFAULT_OWNER_ID
from normalization.apple import apple_wire_metric
from replay.orchestrator import backfill_metric_from_raw
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from storage.timescale.ingest import (
    fetch_raw_metric_payloads,
    ingest_owner_ids,
    metric_row_counts,
    rows_tagged_with_run,
    supersede_metric_records,
)
from storage.timescale.observations import CanonicalObservationRepository

# Must match apps/api/server/api/ingest.py::APPLE_HEALTHKIT_SOURCE_ID, so
# back-filled rows and live dual-writes are one Apple source with one dedup key.
APPLE_HEALTHKIT_SOURCE_ID = uuid.UUID("a9b1e7e0-0000-4000-8000-000000000001")

# The neighbour a back-fill must leave alone, printed before and after.
GUARD_METRIC = {"vital.hrv_rmssd": "vital.hrv_sdnn"}


class OtherMetricWritten(SystemExit):
    """The run wrote a row of a metric other than the one it back-fills."""


def _counts(label: str, metric_id: str, counts: dict[str, int]) -> str:
    return f"{label} {metric_id}: active={counts['active']} other_status={counts['other_status']}"


async def run(*, wire_metric: str, dry_run: bool, limit: int) -> dict[str, object]:
    definition = apple_wire_metric(wire_metric)
    if definition is None:
        raise SystemExit(
            f"{wire_metric!r} has no canonical metric on this server; nothing to back-fill."
        )
    metric_id = str(definition.id)
    guard_id = GUARD_METRIC.get(metric_id)
    engine = create_async_engine(os.environ["DATABASE_URL"])
    repo = CanonicalObservationRepository()
    run_id = uuid.uuid4()
    mode = "DRY-RUN (rollback)" if dry_run else "COMMIT"
    totals = {
        "pages": 0,
        "scanned": 0,
        "skipped_unknown_owner": 0,
        "produced": 0,
        "rejected": 0,
        "deletions_applied": 0,
        "rows_added": 0,
    }

    async def reader(session: AsyncSession, *, after_id: int = 0, limit: int = limit):
        return await fetch_raw_metric_payloads(
            session, wire_metric=wire_metric, after_id=after_id, limit=limit
        )

    try:
        async with AsyncSession(engine) as session:
            owners = await ingest_owner_ids(session)
            before = await metric_row_counts(
                session, canonical_metric=metric_id, wire_metric=wire_metric
            )
            guard_before = (
                await metric_row_counts(session, canonical_metric=guard_id) if guard_id else None
            )
        # A batch without a receipt owner may only be the default owner's
        # when nobody else holds a key or has synced here.
        fallback = DEFAULT_OWNER_ID if owners <= {DEFAULT_OWNER_ID} else None
        print(
            f"backfill start: mode={mode} run_id={run_id} wire={wire_metric} "
            f"metric={metric_id} owners={len(owners)} receiptless_batches_go_to="
            f"{'default owner' if fallback else 'nobody (skipped)'}",
            flush=True,
        )
        print(f"before: raw rows {wire_metric}={before['raw_rows']}", flush=True)
        print(_counts("before:", metric_id, before), flush=True)
        if guard_before:
            print(_counts("before: guard", guard_id, guard_before), flush=True)

        cursor = 0
        while True:
            async with AsyncSession(engine) as session:
                tagged_before = await rows_tagged_with_run(session, run_id=run_id)
                report = await backfill_metric_from_raw(
                    session,
                    raw_reader=reader,
                    repo=repo,
                    superseder=supersede_metric_records,
                    run_id=run_id,
                    source_id=APPLE_HEALTHKIT_SOURCE_ID,
                    metric_id=metric_id,
                    fallback_owner_id=fallback,
                    after_id=cursor,
                    limit=limit,
                )
                # Counted inside the page's own transaction: a dry run shows
                # what it would add, and the check holds before any commit.
                tagged = await rows_tagged_with_run(session, run_id=run_id)
                strays = {m: n for m, n in tagged.items() if m != metric_id}
                if strays:
                    await session.rollback()
                    raise OtherMetricWritten(
                        f"run {run_id} wrote rows of other metrics {strays}; "
                        "page rolled back, back-fill stopped"
                    )
                page_added = tagged.get(metric_id, 0) - tagged_before.get(metric_id, 0)
                if dry_run:
                    await session.rollback()
                else:
                    await session.commit()
            if report.payloads_scanned == 0:
                break
            totals["pages"] += 1
            totals["scanned"] += report.payloads_scanned
            totals["skipped_unknown_owner"] += report.payloads_skipped_unknown_owner
            totals["produced"] += report.observations_produced
            totals["rejected"] += report.observations_rejected
            totals["deletions_applied"] += report.deletions_applied
            totals["rows_added"] += page_added
            cursor = report.last_raw_id
            print(
                f"page {totals['pages']}: batches={report.payloads_scanned} "
                f"readings={report.observations_produced} rows_added={page_added} "
                f"deletions_applied={report.deletions_applied} "
                f"skipped_unknown_owner={report.payloads_skipped_unknown_owner} "
                f"next_cursor={cursor}",
                flush=True,
            )

        async with AsyncSession(engine) as session:
            after = await metric_row_counts(
                session, canonical_metric=metric_id, wire_metric=wire_metric
            )
            guard_after = (
                await metric_row_counts(session, canonical_metric=guard_id) if guard_id else None
            )
    finally:
        await engine.dispose()

    print(_counts("after:", metric_id, after), flush=True)
    if guard_after:
        print(_counts("after: guard", guard_id, guard_after), flush=True)
    print(
        f"backfill done: mode={mode} pages={totals['pages']} batches={totals['scanned']} "
        f"readings={totals['produced']} rejected={totals['rejected']} "
        f"deletions_applied={totals['deletions_applied']} "
        f"skipped_unknown_owner={totals['skipped_unknown_owner']} "
        f"rows_{'that_would_be_' if dry_run else ''}added={totals['rows_added']}",
        flush=True,
    )
    return {"run_id": str(run_id), "before": before, "after": after, **totals}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Back-fill one metric's stored raw batches into canonical readings."
    )
    ap.add_argument(
        "--metric",
        required=True,
        help="wire metric name, e.g. heart_rate_variability_rmssd",
    )
    ap.add_argument("--dry-run", action="store_true", help="normalize but roll back every page")
    ap.add_argument("--limit", type=int, default=200, help="raw batches per page (default 200)")
    args = ap.parse_args()
    asyncio.run(run(wire_metric=args.metric, dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
