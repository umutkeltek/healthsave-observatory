"""Back-fill Whoop recovery readings older versions stored but never showed.

Up to 1.5.3 the Whoop connector wrote recovery HRV, resting heart rate and
blood oxygen only into the older per-metric tables (``hrv`` /
``quantity_samples`` / ``blood_oxygen``), which no page, metric list or AI
connector reads. This turns those rows into canonical readings on the Whoop
stream, exactly as the connector now writes new ones
(``plugins.sources.whoop.normalize.recovery_observation``):

* HRV -> ``vital.hrv_rmssd`` (Whoop measures RMSSD; it is never written as
  SDNN, even though versions up to 1.5.2 stored it in the SDNN ``hrv`` table);
* resting heart rate -> ``vital.resting_heart_rate``;
* blood oxygen -> ``vital.blood_oxygen``.

Safe by construction:

* reads only rows the Whoop connector wrote (device ``Whoop`` and source
  ``Whoop``); Apple Watch and iPhone rows are never read;
* add-only: same key as the live connector (Whoop source, metric, timestamp)
  through the idempotent canonical insert, which never rewrites a Whoop row;
  a second run adds nothing, and a reading the connector already wrote is
  not added twice;
* the run checks, before committing, that it wrote rows of those three
  metrics only, and stops with everything rolled back if not.

Run inside the api container::

    python -m scripts.backfill_whoop_recovery --dry-run
    python -m scripts.backfill_whoop_recovery
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from storage.timescale.ingest import fetch_whoop_legacy_recovery_rows, rows_tagged_with_run
from storage.timescale.observations import CanonicalObservationRepository

from plugins.sources.whoop.normalize import RECOVERY_METRIC_IDS, recovery_observation

KIND_TO_METRIC = {
    "hrv_rmssd": "vital.hrv_rmssd",
    "resting_heart_rate": "vital.resting_heart_rate",
    "blood_oxygen": "vital.blood_oxygen",
}
BATCH = 500


class OtherMetricWritten(SystemExit):
    """The run wrote a row of a metric other than the three it back-fills."""


def build_observations(
    rows: list[tuple[uuid.UUID, str, Any, float]], *, run_id: uuid.UUID
) -> tuple[list[Any], Counter]:
    """Legacy rows -> canonical observations tagged with the run; skipped counted."""

    captured_at = datetime.now(UTC)
    out: list[Any] = []
    skipped: Counter = Counter()
    for owner_id, kind, at, value in rows:
        metric_id = KIND_TO_METRIC.get(kind)
        if metric_id is None:
            skipped[f"unknown:{kind}"] += 1
            continue
        obs = recovery_observation(
            owner_id=owner_id,
            metric_id=metric_id,
            value=value,
            at=at,
            captured_at=captured_at,
            provenance_ref="backfill:legacy-table",
        )
        if obs is None:
            skipped[f"out_of_range:{metric_id}"] += 1
            continue
        out.append(obs.model_copy(update={"normalization_run_id": run_id}))
    return out, skipped


async def run(*, dry_run: bool) -> dict[str, Any]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    repo = CanonicalObservationRepository()
    run_id = uuid.uuid4()
    mode = "DRY-RUN (rollback)" if dry_run else "COMMIT"
    try:
        async with AsyncSession(engine) as session:
            rows = await fetch_whoop_legacy_recovery_rows(session)
            observations, skipped = build_observations(rows, run_id=run_id)
            found = Counter(KIND_TO_METRIC.get(kind, kind) for _, kind, _, _ in rows)
            print(
                f"backfill start: mode={mode} run_id={run_id} "
                f"whoop_rows_found={len(rows)} by_metric={dict(sorted(found.items()))} "
                f"owners={len({owner for owner, *_ in rows})}",
                flush=True,
            )
            for i in range(0, len(observations), BATCH):
                await repo.insert_many(session, observations[i : i + BATCH])
            # Only rows this run actually inserted carry its run id: a reading
            # already present (written by the connector or a first run) is
            # left as it was by the insert, so it is not counted.
            added = await rows_tagged_with_run(session, run_id=run_id)
            strays = {m: n for m, n in added.items() if m not in RECOVERY_METRIC_IDS}
            if strays:
                await session.rollback()
                raise OtherMetricWritten(
                    f"run {run_id} wrote rows of other metrics {strays}; rolled back"
                )
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
    finally:
        await engine.dispose()
    total = sum(added.values())
    print(
        f"backfill done: mode={mode} readings_built={len(observations)} "
        f"skipped={dict(skipped)} rows_{'that_would_be_' if dry_run else ''}added={total} "
        f"by_metric={dict(sorted(added.items()))}",
        flush=True,
    )
    return {"run_id": str(run_id), "found": len(rows), "added": dict(added), "skipped": skipped}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Back-fill Whoop recovery readings from the older per-metric tables."
    )
    ap.add_argument("--dry-run", action="store_true", help="build and insert, then roll back")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
