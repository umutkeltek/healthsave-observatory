#!/usr/bin/env python3
"""Seed a throwaway LOCAL Observatory with a SYNTHETIC year (demos and e2e).

Every value comes from a seeded random generator; none is a person's. It
covers January 1 of this year to today and tells a device story the year view
and the MCP tools can show:

* Apple Watch Series 9 until September 13, Apple Watch Series 11 from
  September 14 (a new watch)
* Oura Ring from April 10 (a second source; never averaged with the watch)
* Withings Body+ every third day, iPhone day totals for steps and energy
* August 3 - August 11: nothing at all (everything left at home)
* March 14 - March 15: the watch is off; the phone still counts steps

It posts through the shipped v1 batch route, so data lands under the owner
of the key it is given (a participant key keeps a demo apart from your own).
It refuses any host but this machine.

Usage: python -m scripts.seed_synthetic_year http://127.0.0.1:8000 <API_KEY>
"""

from __future__ import annotations

import datetime as dt
import json
import math
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

WATCH_OLD, WATCH_NEW, RING, SCALE = (
    "Apple Watch Series 9",
    "Apple Watch Series 11",
    "Oura Ring",
    "Withings Body+",
)
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _between(day: dt.date, span: tuple[dt.date, dt.date]) -> bool:
    return span[0] <= day <= span[1]


def build(now: dt.datetime | None = None) -> tuple[dict[str, list[dict]], dict]:
    """The synthetic samples per v1 metric, and a summary of what they hold."""

    rng = random.Random(20261102)
    now = now or dt.datetime.now(dt.UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today.replace(month=1, day=1)
    days = (today - start).days
    new_watch_from = dt.date(start.year, 9, 14)
    ring_from = dt.date(start.year, 4, 10)
    off = (dt.date(start.year, 8, 3), dt.date(start.year, 8, 11))
    watch_off = (dt.date(start.year, 3, 14), dt.date(start.year, 3, 15))

    def wave(day: int, period: float, amp: float) -> float:
        return amp * math.sin(2 * math.pi * day / period)

    def strain(day: int) -> float:
        """A hard block in late October, so the engine has a real change to find."""

        return 1.0 if 12 <= days - day <= 18 else 0.0

    names = ("hr", "rhr", "rhr_ring", "hrv", "hrv_ring", "resp", "spo2", "steps", "energy")
    s: dict[str, list[dict]] = {name: [] for name in names}
    walk_hr, sleep, weight, vo2, summaries = [], [], [], [], []
    nights: list[str] = []

    for d in range(days + 1):
        day = start + dt.timedelta(days=d)
        date = day.date()
        if _between(date, off):
            continue
        st = strain(d)
        watch = WATCH_NEW if date >= new_watch_from else WATCH_OLD
        watch_on = not _between(date, watch_off)
        ring_on = date >= ring_from
        base_rhr = 56 + wave(d, 46, 1.4) + 4.6 * st + rng.gauss(0, 0.8)
        base_hrv = 51 + wave(d, 38, 3.2) - 11 * st + rng.gauss(0, 2.2)
        trained = d % 7 in (1, 3, 5)

        if watch_on:
            s["rhr"].append(
                {"date": _iso(day + dt.timedelta(hours=6)), "qty": round(base_rhr), "source": watch}
            )
            s["hrv"].append(
                {
                    "date": _iso(day + dt.timedelta(hours=5)),
                    "qty": round(base_hrv, 1),
                    "source": watch,
                }
            )
            s["resp"].append(
                {
                    "date": _iso(day + dt.timedelta(hours=4)),
                    "qty": round(14.4 + 0.9 * st + rng.gauss(0, 0.3), 1),
                    "source": watch,
                }
            )
            s["spo2"].append(
                {
                    "date": _iso(day + dt.timedelta(hours=3)),
                    "qty": round(min(99.0, 97.2 + rng.gauss(0, 0.5)), 1),
                    "source": watch,
                }
            )
            walk_hr.append(
                {
                    "date": _iso(day + dt.timedelta(hours=18)),
                    "qty": round(96 + 5 * st + rng.gauss(0, 2)),
                    "source": watch,
                }
            )
            for hour in range(0, 24):
                for minute in (0, 30):
                    t = day + dt.timedelta(hours=hour, minutes=minute)
                    if t > now:
                        continue
                    circ = 11 * math.sin((hour - 9) / 24 * 2 * math.pi) + 11
                    bump = 34 if trained and hour == 18 else 0
                    s["hr"].append(
                        {
                            "date": _iso(t),
                            "qty": round(base_rhr + circ + bump + rng.gauss(0, 3.5)),
                            "source": watch,
                        }
                    )
        if ring_on:
            s["rhr_ring"].append(
                {
                    "date": _iso(day + dt.timedelta(hours=6, minutes=30)),
                    "qty": round(base_rhr - 2.4 + rng.gauss(0, 0.6)),
                    "source": RING,
                }
            )
            s["hrv_ring"].append(
                {
                    "date": _iso(day + dt.timedelta(hours=5, minutes=30)),
                    "qty": round(base_hrv + 7.5 + rng.gauss(0, 2), 1),
                    "source": RING,
                }
            )
        if d < days:
            n_steps = max(
                2400, int(rng.gauss(10800 if trained else 7600, 1700) * (0.8 if st else 1))
            )
            active = round(n_steps * 0.044 + (240 if trained else 30) + rng.gauss(0, 30), 1)
            s["steps"].append({"date": _iso(day), "qty": n_steps, "source": "HealthKit Statistics"})
            s["energy"].append({"date": _iso(day), "qty": active, "source": "HealthKit Statistics"})
            if watch_on:
                summaries.append(
                    {
                        "date": _iso(day),
                        "activeEnergyBurned": active,
                        "activeEnergyBurnedGoal": 620,
                        "appleExerciseTime": 48 if trained else int(rng.gauss(18, 5)),
                        "appleExerciseTimeGoal": 30,
                        "appleStandHours": rng.randint(8, 13),
                        "appleStandHoursGoal": 12,
                    }
                )
        if d % 3 == 0:
            weight.append(
                {
                    "date": _iso(day + dt.timedelta(hours=7)),
                    "qty": round(74.4 - d * 0.004 + rng.gauss(0, 0.25), 1),
                    "source": SCALE,
                }
            )
        if d % 14 == 0 and watch_on:
            vo2.append(
                {
                    "date": _iso(day + dt.timedelta(hours=19)),
                    "qty": round(44.2 + d * 0.004 + rng.gauss(0, 0.2), 1),
                    "source": watch,
                }
            )
        if d < days and watch_on:
            bed = day + dt.timedelta(hours=22, minutes=int(rng.gauss(50, 22)))
            cursor, total = bed, int(rng.gauss(445 - 45 * st, 24))
            end_at = bed + dt.timedelta(minutes=total)
            cycle = [
                "Core",
                "Deep",
                "Core",
                "REM",
                "Core",
                "Deep",
                "Core",
                "REM",
                "Awake",
                "Core",
                "REM",
            ]
            i = 0
            while cursor < end_at:
                stage = cycle[i % len(cycle)]
                mins = {"Core": 44, "Deep": 26, "REM": 24, "Awake": 5}[stage] + rng.randint(-5, 5)
                stop = min(end_at, cursor + dt.timedelta(minutes=max(3, mins)))
                sleep.append(
                    {
                        "startDate": _iso(cursor),
                        "endDate": _iso(stop),
                        "value": stage,
                        "source": watch,
                    }
                )
                cursor, i = stop, i + 1
            nights.append(date.isoformat())  # the evening the night belongs to

    batches = {
        "heart_rate": s["hr"],
        "resting_heart_rate": s["rhr"] + s["rhr_ring"],
        "heart_rate_variability": s["hrv"] + s["hrv_ring"],
        "respiratory_rate": s["resp"],
        "oxygen_saturation": s["spo2"],
        "walking_heart_rate_average": walk_hr,
        "step_count": s["steps"],
        "active_energy_burned": s["energy"],
        "body_mass": weight,
        "vo2_max": vo2,
        "sleep_analysis": sleep,
        "activity_summaries": summaries,
    }
    # Nothing from the future: today's evening readings wait for the clock.
    cutoff = _iso(now)
    batches = {
        metric: [x for x in samples if (x.get("date") or x.get("startDate")) <= cutoff]
        for metric, samples in batches.items()
    }
    summary = {
        "year": start.year,
        "nights": nights,
        "nothing_recorded": [off[0].isoformat(), off[1].isoformat()],
        "watch_off": [watch_off[0].isoformat(), watch_off[1].isoformat()],
    }
    return batches, summary


def post(base_url: str, api_key: str, metric: str, samples: list[dict], size: int = 800) -> None:
    host = urllib.parse.urlparse(base_url).hostname
    if host not in LOOPBACK:
        raise SystemExit(f"refusing non-loopback host: {host}")
    chunks = [samples[i : i + size] for i in range(0, len(samples), size)] or [[]]
    for index, chunk in enumerate(chunks):
        body = json.dumps(
            {"metric": metric, "batch_index": index, "total_batches": len(chunks), "samples": chunk}
        ).encode()
        request = urllib.request.Request(
            base_url.rstrip("/") + "/api/apple/batch",
            data=body,
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"{metric} batch {index}: HTTP {exc.code} {exc.read()[:300]!r}"
            ) from exc


def seed(base_url: str, api_key: str, now: dt.datetime | None = None, quiet: bool = True) -> dict:
    """Post the synthetic year; return what it holds (nights, the empty days)."""

    host = urllib.parse.urlparse(base_url).hostname
    if host not in LOOPBACK:
        raise SystemExit(f"refusing non-loopback host: {host}")
    batches, summary = build(now)
    for metric, samples in batches.items():
        post(base_url, api_key, metric, samples)
        if not quiet:
            print(f"{metric}: {len(samples)} samples")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    summary = seed(args[0], args[1], quiet=False)
    print(f"synthetic year {summary['year']}: {len(summary['nights'])} nights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
