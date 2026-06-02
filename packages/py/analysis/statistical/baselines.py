"""Rolling baseline computation — the reusable statistical core.

Every brain (anomaly, scoring, correlation) compares "today" against a
*personal rolling baseline*. The math behind that comparison — mean, sample
standard deviation, and a few percentiles over a window of samples — is the
same everywhere, so it lives here once as a **pure** function rather than being
re-derived inline in each detector.

Two deliberate boundaries:

* **No I/O.** This module never touches SQLAlchemy. It computes over whatever
  ``(timestamp, value)`` samples it's handed; *fetching* the window is a
  storage-zone concern the caller injects (see :class:`BaselineTracker`). This
  keeps the sealed storage zone sealed.
* **Per device.** Baselines are computed PER DEVICE (supplement §5.5):
  switching from an Apple Watch to a Whoop starts a fresh baseline rather than
  silently mixing two sensors' systematic offsets. This module computes over
  one device's samples; the caller is responsible for scoping the window to a
  single device.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import datetime

# One observation: when it happened and its value. The timestamp is retained so
# the "distinct days" sufficiency signal can be derived without a second pass.
Sample = tuple["datetime", float]


@dataclass(frozen=True)
class Baseline:
    """Distribution summary of one metric over a rolling window.

    ``stddev`` is the *sample* standard deviation (n-1 / Bessel's correction);
    it is ``0.0`` for a single sample. Percentiles use linear interpolation
    between closest ranks (numpy's default), so they degrade gracefully on
    small windows.
    """

    mean: float
    stddev: float
    p10: float
    p50: float
    p90: float
    n: int
    days: int

    def zscore(self, value: float) -> float | None:
        """Standard score of ``value`` against this baseline.

        Returns ``None`` for a degenerate (zero-variance) baseline, where a
        z-score is undefined — callers must treat that as "cannot judge",
        never as "zero deviation".
        """
        if self.stddev == 0:
            return None
        return (value - self.mean) / self.stddev


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted list.

    ``pct`` is a fraction in [0, 1]. Matches numpy's default ``linear``
    interpolation so percentiles are comparable across the codebase.
    """
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def compute_baseline(samples: Sequence[Sample]) -> Baseline | None:
    """Summarize ``samples`` into a :class:`Baseline`, or ``None`` if empty.

    Pure: no clock, no I/O. ``stddev`` is the sample standard deviation
    (``0.0`` for a single sample), matching the previous inline anomaly math.
    """
    if not samples:
        return None
    values = sorted(value for _, value in samples)
    n = len(values)
    return Baseline(
        mean=statistics.fmean(values),
        stddev=statistics.stdev(values) if n > 1 else 0.0,
        p10=_percentile(values, 0.10),
        p50=_percentile(values, 0.50),
        p90=_percentile(values, 0.90),
        n=n,
        days=len({timestamp.date() for timestamp, _ in samples}),
    )


class BaselineTracker:
    """Fetch + summarize rolling per-device baselines.

    Data access is **injected** (``fetcher``) rather than performed here, so
    this stays out of the sealed storage zone and unit-tests against fakes with
    no database. ``fetcher(metric, device_id, days)`` returns the window's
    samples; the summary itself is the pure :func:`compute_baseline`.

    Caching (the eventual point of a long-lived *tracker* rather than a bare
    function) is deferred until a caller needs repeated lookups within a run.
    """

    def __init__(
        self,
        fetcher: Callable[[str, int, int], Awaitable[Sequence[Sample]]],
    ) -> None:
        self._fetcher = fetcher

    async def baseline_for(self, metric: str, device_id: int, days: int = 30) -> Baseline | None:
        """Return the rolling baseline for ``metric`` on ``device_id``."""
        samples = await self._fetcher(metric, device_id, days)
        return compute_baseline(samples)
