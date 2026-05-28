"""Import Samsung Health / Huawei Health CSV exports into Health Data Hub.

Reads the directory layout that the `Health Sync` app on Android produces,
parses each CSV into HealthSave-shaped samples, and POSTs them to
``/api/apple/batch`` in batches. The server handles dedup, audit log,
sync receipts, and per-metric routing — same path the iOS app uses.

Supported categories (any combination present in the source directory):

    Health Sync Steps/             -> metric: step_count
    Health Sync Heart rate/        -> metric: heart_rate
    Health Sync Sleep/             -> metric: sleep_analysis
    Health Sync Weight/            -> metrics: body_mass, body_fat_percentage
    Health Sync Oxygen saturation/ -> metric: oxygen_saturation

Source attribution is read from each file's name — Health Sync includes
``"Samsung Health"`` or ``"Huawei Health"`` in the file name, and the
importer surfaces that as the sample's ``source`` field so downstream
dashboards can split per vendor.

Examples::

    python scripts/import_samsung.py /path/to/samsung_data \\
        --server http://localhost:8000 --api-key $HDH_API_KEY

    python scripts/import_samsung.py /path/to/samsung_data --dry-run

The ``--dry-run`` mode parses + counts + logs but never POSTs; useful
for sanity-checking a fresh export before sending real traffic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any

import httpx

log = logging.getLogger("import_samsung")

# Health Sync date formats observed across years:
#   '2019.11.29 00.50'        (Samsung old: dots everywhere)
#   '2024.12.30 05:43:00'     (Huawei: dots date, colons time + seconds)
#   '2024.01.03 00.20'        (Samsung new: dots time without seconds)
#   '2024.01.03 00:20:00'     (Samsung new: colons time with seconds)
_DATE_FORMATS = (
    "%Y.%m.%d %H.%M",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H.%M.%S",
    "%Y.%m.%d %H:%M",
)

_SOURCE_PATTERNS = (
    (re.compile(r"Samsung Health", re.IGNORECASE), "Samsung Health"),
    (re.compile(r"Huawei Health", re.IGNORECASE), "Huawei Health"),
)


@dataclass
class Sample:
    """One row destined for ``/api/apple/batch`` under ``metric``."""

    metric: str
    payload: dict[str, Any]


@dataclass
class ParseResult:
    """Accumulator the directory walker fills as it traverses the input."""

    samples: list[Sample] = field(default_factory=list)

    def extend(self, more: Iterable[Sample]) -> None:
        self.samples.extend(more)


def parse_date(value: str) -> datetime | None:
    """Parse one of the Health Sync timestamp formats into a UTC datetime."""
    value = value.strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def extract_source(filename: str) -> str:
    """Pull the vendor name out of a Health Sync filename. ``Unknown`` as a fallback."""
    name = Path(filename).stem
    for pattern, label in _SOURCE_PATTERNS:
        if pattern.search(name):
            return label
    return "Unknown"


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ─── Per-category parsers ────────────────────────────────────────────


def parse_steps_csv(fh: IO[str], *, source: str) -> Iterator[Sample]:
    """Each row is a 10-minute step bucket; emit one ``step_count`` per row.

    ``batches_for`` folds these bucket rows into one daily total per source
    before posting, because the server stores ``step_count`` as
    ``daily_activity.steps`` rather than as interval samples.
    """
    reader = csv.DictReader(fh)
    for row in reader:
        dt = parse_date(row.get("Date", ""))
        if dt is None:
            continue
        try:
            steps = int(float(row.get("Steps", 0)))
        except (TypeError, ValueError):
            continue
        if steps <= 0:
            continue
        yield Sample(
            metric="step_count",
            payload={"date": _iso_z(dt), "qty": steps, "source": source, "unit": "count"},
        )


def parse_heart_rate_csv(fh: IO[str], *, source: str) -> Iterator[Sample]:
    """One ``heart_rate`` sample per row, with ``context='continuous'``.

    Samsung/Huawei watches log continuous HR; the source dashboards
    expect ``context='resting'`` rows for resting-HR panels — those
    come from a separate Samsung 'Heart rate resting' export, which
    Health Sync emits in a parallel directory. The default here labels
    every row 'continuous' so dashboards do not silently mislabel.
    """
    reader = csv.DictReader(fh)
    for row in reader:
        dt = parse_date(row.get("Date", ""))
        if dt is None:
            continue
        try:
            bpm = int(float(row.get("Heart rate", 0)))
        except (TypeError, ValueError):
            continue
        if bpm <= 0 or bpm > 250:
            continue
        yield Sample(
            metric="heart_rate",
            payload={
                "date": _iso_z(dt),
                "qty": bpm,
                "source": source,
                "context": "continuous",
                "unit": "count/min",
            },
        )


def parse_sleep_csv(fh: IO[str], *, source: str) -> Iterator[Sample]:
    """Each row is one sleep-stage segment with a start time + duration.

    Emits ``sleep_analysis`` samples in the HealthKit-shaped form the
    server's sleep handler accepts:

        {"start": <iso>, "end": <iso>, "value": <stage>, "source": ...}
    """
    reader = csv.DictReader(fh)
    for row in reader:
        dt = parse_date(row.get("Date", ""))
        if dt is None:
            continue
        try:
            duration_s = int(float(row.get("Duration in seconds", 0)))
        except (TypeError, ValueError):
            continue
        if duration_s <= 0:
            continue
        stage = (row.get("Sleep stage") or "unknown").strip().lower()
        end = dt + timedelta(seconds=duration_s)
        yield Sample(
            metric="sleep_analysis",
            payload={
                "start": _iso_z(dt),
                "end": _iso_z(end),
                "value": stage,
                "source": source,
            },
        )


def parse_weight_csv(fh: IO[str], *, source: str) -> Iterator[Sample]:
    """Body mass + optional body-fat percentage from the same row.

    The server stores both in ``quantity_samples`` keyed on
    ``metric_name``; no aggregation other than its standard dedup.
    """
    reader = csv.DictReader(fh)
    for row in reader:
        dt = parse_date(row.get("Date", ""))
        if dt is None:
            continue
        when = _iso_z(dt)

        weight_str = (row.get("Weight") or "").strip().strip('"')
        try:
            weight = float(weight_str)
        except ValueError:
            weight = 0.0
        if weight > 0:
            yield Sample(
                metric="body_mass",
                payload={"date": when, "qty": weight, "source": source, "unit": "kg"},
            )

        bf_str = (row.get("Body fat percentage") or "").strip().strip('"')
        try:
            bf = float(bf_str)
        except ValueError:
            bf = 0.0
        if bf > 0:
            yield Sample(
                metric="body_fat_percentage",
                payload={"date": when, "qty": bf, "source": source, "unit": "%"},
            )


def parse_spo2_csv(fh: IO[str], *, source: str) -> Iterator[Sample]:
    """Overnight oxygen-saturation readings. Server aliases to ``blood_oxygen``."""
    reader = csv.DictReader(fh)
    for row in reader:
        dt = parse_date(row.get("Date", ""))
        if dt is None:
            continue
        try:
            spo2 = float(row.get("Oxygen saturation", 0))
        except (TypeError, ValueError):
            continue
        if spo2 <= 0 or spo2 > 100:
            continue
        yield Sample(
            metric="oxygen_saturation",
            payload={
                "date": _iso_z(dt),
                "qty": spo2,
                "source": source,
                "context": "overnight",
                "unit": "%",
            },
        )


# Directory subname -> (parser, label) for the walker.
_CATEGORY_DISPATCH: dict[str, tuple[Any, str]] = {
    "Health Sync Steps": (parse_steps_csv, "steps"),
    "Health Sync Heart rate": (parse_heart_rate_csv, "heart_rate"),
    "Health Sync Sleep": (parse_sleep_csv, "sleep"),
    "Health Sync Weight": (parse_weight_csv, "weight"),
    "Health Sync Oxygen saturation": (parse_spo2_csv, "spo2"),
}


def walk_directory(root: Path) -> ParseResult:
    """Iterate the Health Sync subdirectories under ``root`` and parse every CSV."""
    result = ParseResult()
    if not root.is_dir():
        raise FileNotFoundError(root)

    for subname, (parser, label) in _CATEGORY_DISPATCH.items():
        subdir = root / subname
        if not subdir.is_dir():
            log.info("skip %s (no directory)", label)
            continue
        csv_files = sorted(subdir.glob("*.csv"))
        if not csv_files:
            log.info("skip %s (no csv files)", label)
            continue
        log.info("found %d %s csv file(s)", len(csv_files), label)
        for path in csv_files:
            source = extract_source(path.name)
            with path.open(newline="", encoding="utf-8-sig") as fh:
                result.extend(parser(fh, source=source))
    return result


# ─── Batching + POST (mirrors import_garmin) ────────────────────────────


def batches_for(samples: Iterable[Sample], *, batch_size: int = 500) -> Iterator[dict[str, Any]]:
    """Group samples by metric, then by ``batch_size`` chunks."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in _normalize_samples_for_server(samples):
        buckets[sample.metric].append(sample.payload)

    for metric, payloads in buckets.items():
        chunks = [payloads[i : i + batch_size] for i in range(0, len(payloads), batch_size)] or [[]]
        total = len(chunks)
        for index, chunk in enumerate(chunks):
            yield {
                "metric": metric,
                "batch_index": index,
                "total_batches": total,
                "samples": chunk,
            }


def _normalize_samples_for_server(samples: Iterable[Sample]) -> list[Sample]:
    """Adapt parsed Health Sync rows to Data Hub's storage grain.

    Health Sync exports steps as interval buckets. Data Hub's ``step_count``
    path is daily-activity storage, so sending bucket rows would repeatedly
    overwrite a day's total with the current bucket. Aggregate by UTC day and
    source first; all other metrics already match the server's sample grain.
    """
    normalized: list[Sample] = []
    step_totals: dict[tuple[str, str], int] = defaultdict(int)
    step_units: dict[tuple[str, str], str] = {}

    for sample in samples:
        if sample.metric != "step_count":
            normalized.append(sample)
            continue

        payload = sample.payload
        raw_date = str(payload.get("date") or "")
        day = raw_date.split("T", 1)[0]
        if not day:
            normalized.append(sample)
            continue
        source = str(payload.get("source") or "")
        key = (day, source)
        step_totals[key] += int(payload.get("qty") or 0)
        step_units.setdefault(key, str(payload.get("unit") or "count"))

    for (day, source), total in step_totals.items():
        normalized.append(
            Sample(
                metric="step_count",
                payload={
                    "date": day,
                    "qty": total,
                    "source": source,
                    "unit": step_units[(day, source)],
                },
            )
        )

    return normalized


def post_batches(
    batches: Iterable[dict[str, Any]],
    *,
    base_url: str,
    api_key: str | None = None,
    sync_run_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 120.0,
    progress_every: int = 25,
) -> tuple[int, int]:
    """POST each batch to ``/api/apple/batch``. Returns ``(batches_sent, samples_sent)``."""
    base_headers = {"Content-Type": "application/json"}
    if api_key:
        base_headers["x-api-key"] = api_key
    if sync_run_id:
        base_headers["X-HealthSave-Sync-Run-ID"] = sync_run_id
        base_headers["X-HealthSave-Sync-Mode"] = "historical_import"
        base_headers["X-HealthSave-Full-Export"] = "true"

    sent_batches = 0
    sent_records = 0
    with httpx.Client(transport=transport, timeout=timeout) as client:
        for batch in batches:
            headers = dict(base_headers)
            if sync_run_id:
                batch_id = f"{sync_run_id}:{batch['metric']}:{batch['batch_index']}"
                payload_hash = _payload_hash(batch)
                headers.update(
                    {
                        "Idempotency-Key": batch_id,
                        "X-HealthSave-Batch-ID": batch_id,
                        "X-HealthSave-Payload-Hash": payload_hash,
                        "X-HealthSave-Metric": str(batch["metric"]),
                        "X-HealthSave-Batch-Index": str(batch["batch_index"]),
                        "X-HealthSave-Total-Batches": str(batch["total_batches"]),
                    }
                )
            response = client.post(
                f"{base_url.rstrip('/')}/api/apple/batch",
                json=batch,
                headers=headers,
            )
            response.raise_for_status()
            sent_batches += 1
            sent_records += len(batch["samples"])
            if progress_every > 0 and sent_batches % progress_every == 0:
                log.info("sent %d batch(es), %d sample(s)", sent_batches, sent_records)
    return sent_batches, sent_records


def _payload_hash(batch: dict[str, Any]) -> str:
    payload = json.dumps(batch, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# ─── CLI ─────────────────────────────────────────────────────────────


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_samsung",
        description="Import Samsung / Huawei Health Sync CSV exports into Health Data Hub.",
    )
    parser.add_argument("data_dir", help="Directory containing the Health Sync subfolders")
    parser.add_argument(
        "--server",
        default=os.environ.get("HDH_SERVER", "http://localhost:8000"),
        help="Base URL of the Health Data Hub API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("HDH_API_KEY"),
        help="HDH API key (X-API-Key). Required when the server has API_KEY set.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Samples per /api/apple/batch POST (default: 500)",
    )
    parser.add_argument(
        "--sync-run-id",
        default=os.environ.get("HDH_SYNC_RUN_ID"),
        help="Stable sync run id used for receipts and retry-safe idempotency headers.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("HDH_TIMEOUT", "120")),
        help="Per-request timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=int(os.environ.get("HDH_PROGRESS_EVERY", "25")),
        help="Log progress every N posted batches; 0 disables progress logs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse + count + log only; never POST.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    root = Path(args.data_dir)
    log.info("parsing Health Sync export at %s", root)
    try:
        result = walk_directory(root)
    except FileNotFoundError as e:
        log.error("not a directory: %s", e)
        return 1

    if not result.samples:
        log.warning("no samples parsed — check the directory layout")
        return 0

    per_metric: dict[str, int] = defaultdict(int)
    for s in result.samples:
        per_metric[s.metric] += 1
    for metric, count in sorted(per_metric.items()):
        log.info("  %s: %d sample(s)", metric, count)

    if args.dry_run:
        log.info("dry-run: not POSTing.")
        return 0

    log.info("POSTing to %s", args.server)
    sent_batches, sent_records = post_batches(
        batches_for(result.samples, batch_size=args.batch_size),
        base_url=args.server,
        api_key=args.api_key,
        sync_run_id=args.sync_run_id,
        timeout=args.timeout,
        progress_every=args.progress_every,
    )
    log.info("sent %d batch(es) carrying %d sample(s)", sent_batches, sent_records)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
