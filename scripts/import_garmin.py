"""Import Garmin Connect exports into Health Data Hub.

Reads Garmin Connect "Export Your Data" archives (or individual files) and
POSTs the contents to ``/api/apple/batch`` using the same payload shape the
HealthSave iOS app uses. The server handles the rest.

Supported inputs (any combination):

    --zip <path>          Garmin Connect bulk export ZIP
    --fit <path>          Single FIT activity file (heart rate)
    --tcx <path>          Single TCX activity file (heart rate)
    --steps-json <path>   JSON file with daily step totals
    --sleep-json <path>   JSON file with sleep stages

Mapping:

    FIT/TCX heart-rate records  -> metric: "heart_rate"
    Daily step totals (JSON)    -> metric: "step_count"
    Sleep stages (JSON)         -> metric: "sleep_analysis"

FIT parsing requires the ``garmin`` extra::

    pip install -e ".[garmin]"

TCX, JSON, and ZIP handling use only the standard library.

Examples::

    python scripts/import_garmin.py --zip GarminConnect_Export.zip \\
        --server http://localhost:8000 --api-key $HDH_API_KEY

    python scripts/import_garmin.py --tcx run.tcx --dry-run

    python scripts/import_garmin.py --steps-json steps.json --sleep-json sleep.json
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger("import_garmin")

TCX_NS = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}

# Garmin sleepLevels.activityLevel -> HealthSave sleep stage name.
# 0 = deep, 1 = light, 2 = REM, 3 = awake. The server treats "core" / "light"
# / "asleep" identically, so we standardise on the HealthSave-canonical names.
GARMIN_SLEEP_LEVEL_TO_STAGE: dict[float, str] = {
    0.0: "deep",
    1.0: "light",
    2.0: "rem",
    3.0: "awake",
}


@dataclass
class Sample:
    metric: str
    payload: dict[str, Any]


@dataclass
class ParseResult:
    samples: list[Sample] = field(default_factory=list)

    def extend(self, more: Iterable[Sample]) -> None:
        self.samples.extend(more)


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms_to_iso(ms: float) -> str:
    return _iso(datetime.fromtimestamp(ms / 1000.0, tz=UTC))


def parse_tcx(text: str, source: str = "Garmin") -> Iterator[Sample]:
    """Yield heart-rate samples from a TCX document."""
    root = ET.fromstring(text)
    for trackpoint in root.iter(f"{{{TCX_NS['tcx']}}}Trackpoint"):
        time_el = trackpoint.find("tcx:Time", TCX_NS)
        hr_el = trackpoint.find("tcx:HeartRateBpm/tcx:Value", TCX_NS)
        if time_el is None or hr_el is None or not (time_el.text and hr_el.text):
            continue
        try:
            bpm = int(hr_el.text)
        except ValueError:
            continue
        yield Sample(
            metric="heart_rate",
            payload={
                "date": _normalise_iso(time_el.text),
                "qty": bpm,
                "unit": "count/min",
                "source": source,
            },
        )


def parse_fit(stream: IO[bytes], source: str = "Garmin") -> Iterator[Sample]:
    """Yield heart-rate samples from a FIT activity stream.

    Requires the optional ``garmin`` extra (``fitparse``).
    """
    try:
        from fitparse import FitFile
    except ImportError as exc:
        raise ImportError(
            "FIT parsing requires the 'garmin' extra: pip install -e \".[garmin]\""
        ) from exc

    fit = FitFile(stream)
    for record in fit.get_messages("record"):
        values = {field.name: field.value for field in record}
        ts = values.get("timestamp")
        bpm = values.get("heart_rate")
        if ts is None or bpm is None:
            continue
        if isinstance(ts, datetime):
            iso = _iso(ts)
        else:
            continue
        yield Sample(
            metric="heart_rate",
            payload={
                "date": iso,
                "qty": int(bpm),
                "unit": "count/min",
                "source": source,
            },
        )


def parse_steps_json(obj: Any, source: str = "Garmin") -> Iterator[Sample]:
    """Yield step_count samples from Garmin's daily steps JSON.

    Garmin's wellness export is a list of ``{"calendarDate": "YYYY-MM-DD",
    "totalSteps": <int>}`` entries (older exports may use ``"steps"`` or
    nest under a wrapper). Both shapes are accepted.
    """
    entries = obj if isinstance(obj, list) else obj.get("dailyStepData", [])
    for entry in entries:
        date = entry.get("calendarDate") or entry.get("date")
        steps = entry.get("totalSteps", entry.get("steps"))
        if date is None or steps is None:
            continue
        yield Sample(
            metric="step_count",
            payload={
                "date": f"{date}T00:00:00Z",
                "qty": int(steps),
                "unit": "count",
                "source": source,
            },
        )


def parse_sleep_json(obj: Any, source: str = "Garmin") -> Iterator[Sample]:
    """Yield sleep_analysis samples from Garmin's sleep export.

    Garmin's sleep payload has ``dailySleepDTO`` with start/end timestamps
    and ``sleepLevels`` — a list of ``{startGMT, endGMT, activityLevel}``
    windows. Each window becomes one HealthSave sleep stage sample.
    Bulk exports may wrap everything in an outer list.
    """
    payloads = obj if isinstance(obj, list) else [obj]
    for daily in payloads:
        levels = daily.get("sleepLevels") or []
        for window in levels:
            start = window.get("startGMT") or window.get("start_gmt")
            end = window.get("endGMT") or window.get("end_gmt")
            level = window.get("activityLevel")
            if start is None or end is None or level is None:
                continue
            stage = GARMIN_SLEEP_LEVEL_TO_STAGE.get(float(level))
            if stage is None:
                continue
            yield Sample(
                metric="sleep_analysis",
                payload={
                    "start_date": _normalise_iso(start),
                    "end_date": _normalise_iso(end),
                    "value": stage,
                    "source": source,
                },
            )


def _normalise_iso(raw: str) -> str:
    """Coerce common timestamp formats into ``YYYY-MM-DDTHH:MM:SSZ``."""
    raw = raw.strip()
    # Garmin sometimes emits epoch milliseconds as a string.
    if raw.isdigit():
        return _ms_to_iso(float(raw))
    # Replace "+00:00" with "Z"; accept either form on input.
    cleaned = raw.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(cleaned)
    except ValueError:
        return raw
    return _iso(ts)


def parse_zip(path: Path, source: str = "Garmin") -> Iterator[Sample]:
    """Walk a Garmin Connect bulk-export ZIP and dispatch each member."""
    with zipfile.ZipFile(path) as zf:
        for member in zf.namelist():
            lower = member.lower()
            if lower.endswith(".fit"):
                with zf.open(member) as fh:
                    yield from parse_fit(io.BytesIO(fh.read()), source=source)
            elif lower.endswith(".tcx"):
                with zf.open(member) as fh:
                    yield from parse_tcx(fh.read().decode("utf-8"), source=source)
            elif lower.endswith(".json"):
                with zf.open(member) as fh:
                    try:
                        obj = json.load(fh)
                    except json.JSONDecodeError:
                        log.warning("skipping non-JSON file %s", member)
                        continue
                if "sleep" in lower:
                    yield from parse_sleep_json(obj, source=source)
                elif re.search(r"step|wellness|udsfile", lower):
                    yield from parse_steps_json(obj, source=source)


def build_batches(samples: Iterable[Sample], *, batch_size: int = 1000) -> Iterator[dict]:
    """Group samples by metric and yield HealthSave batch payloads."""
    buckets: dict[str, list[dict]] = {}
    for sample in samples:
        buckets.setdefault(sample.metric, []).append(sample.payload)

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


def post_batches(
    batches: Iterable[dict],
    *,
    base_url: str,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> tuple[int, int]:
    """POST each batch to ``/api/apple/batch``. Returns ``(batches, records)``."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    sent_batches = 0
    sent_records = 0
    with httpx.Client(transport=transport, timeout=timeout) as client:
        for batch in batches:
            response = client.post(
                f"{base_url.rstrip('/')}/api/apple/batch",
                json=batch,
                headers=headers,
            )
            response.raise_for_status()
            sent_batches += 1
            sent_records += len(batch["samples"])
    return sent_batches, sent_records


def collect_samples(args: argparse.Namespace) -> list[Sample]:
    result = ParseResult()
    if args.zip:
        result.extend(parse_zip(Path(args.zip), source=args.source))
    if args.fit:
        with open(args.fit, "rb") as fh:
            result.extend(parse_fit(fh, source=args.source))
    if args.tcx:
        result.extend(parse_tcx(Path(args.tcx).read_text(encoding="utf-8"), source=args.source))
    if args.steps_json:
        result.extend(
            parse_steps_json(json.loads(Path(args.steps_json).read_text()), source=args.source)
        )
    if args.sleep_json:
        result.extend(
            parse_sleep_json(json.loads(Path(args.sleep_json).read_text()), source=args.source)
        )
    return result.samples


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_garmin",
        description="Import Garmin Connect exports into Health Data Hub.",
    )
    parser.add_argument("--zip", help="Garmin Connect bulk export ZIP")
    parser.add_argument("--fit", help="Single FIT activity file (heart rate)")
    parser.add_argument("--tcx", help="Single TCX activity file (heart rate)")
    parser.add_argument("--steps-json", help="JSON file of daily step totals")
    parser.add_argument("--sleep-json", help="JSON file of sleep stages")
    parser.add_argument(
        "--server",
        default=os.environ.get("HDH_SERVER", "http://localhost:8000"),
        help="Health Data Hub base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("HDH_API_KEY"),
        help="Optional x-api-key header value",
    )
    parser.add_argument(
        "--source",
        default="Garmin",
        help="device_type label for ingested samples (default: Garmin)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Samples per HTTP batch (default: 1000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print batches as JSON to stdout instead of POSTing",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    poster: Callable[..., tuple[int, int]] | None = None,
    out: IO[str] | None = None,
) -> int:
    args = build_arg_parser().parse_args(argv)
    if not (args.zip or args.fit or args.tcx or args.steps_json or args.sleep_json):
        sys.stderr.write("at least one input flag is required\n")
        return 2

    samples = collect_samples(args)
    batches = list(build_batches(samples, batch_size=args.batch_size))

    if args.dry_run:
        sink = out or sys.stdout
        json.dump(batches, sink, indent=2, default=str)
        sink.write("\n")
        return 0

    sender = poster or post_batches
    sent_batches, sent_records = sender(
        batches,
        base_url=args.server,
        api_key=args.api_key,
    )
    log.info("posted %d batches (%d records) to %s", sent_batches, sent_records, args.server)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
