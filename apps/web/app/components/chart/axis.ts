// Axis helpers layered on the scale.ts kernel: value-tick placement and dated
// x-axis ticks. Pure + deterministic (dates formatted in UTC so tests don't
// drift with the runner's timezone). Unit-tested in axis.test.ts.

import { niceTicks } from "./scale";

export type ValueTick = { value: number; frac: number };

// Round-number y-axis ticks with their fractional position across [lo, hi]
// (0 at lo, 1 at hi). Ticks outside the domain are dropped so callers can map
// frac straight onto pixels without clamping.
export function valueTicks(lo: number, hi: number, count = 4): ValueTick[] {
  const span = hi - lo || 1;
  const eps = Math.abs(span) * 1e-9;
  return niceTicks(lo, hi, count)
    .filter((v) => v >= lo - eps && v <= hi + eps)
    .map((value) => ({ value, frac: (value - lo) / span }));
}

// Nudge a set of label positions (same coordinate space as `lo`/`hi`) so no two
// sit closer than `minGap`, preserving input order and clamping into [lo, hi].
// Deterministic: colliding labels are pushed downward, then the whole block is
// shifted back up if it overran `hi`. Used for MultiSeriesChart end-labels so
// two series ending at nearly the same value don't stack on top of each other.
export function declutterLabels(positions: number[], minGap: number, lo: number, hi: number): number[] {
  const clamp = (v: number) => Math.min(hi, Math.max(lo, v));
  if (positions.length <= 1) return positions.map(clamp);

  const order = positions.map((p, i) => ({ p, i })).sort((a, b) => a.p - b.p);
  const placed = order.map((o) => o.p);

  for (let k = 1; k < placed.length; k++) {
    if (placed[k] < placed[k - 1] + minGap) placed[k] = placed[k - 1] + minGap;
  }
  const overflow = placed[placed.length - 1] - hi;
  if (overflow > 0) for (let k = 0; k < placed.length; k++) placed[k] -= overflow;

  const out = new Array<number>(positions.length);
  order.forEach((o, k) => {
    out[o.i] = clamp(placed[k]);
  });
  return out;
}

export type DateTick = { frac: number; label: string };

const MS_DAY = 86_400_000;

function fmt(ms: number, opts: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", ...opts }).format(new Date(ms));
}

// Dated x-axis ticks across [startMs, endMs]. Long windows (>120 days) label the
// first of each month; short windows label evenly spaced day/month marks. `frac`
// is the position 0..1 across the domain. Empty for a degenerate/invalid range.
export function dateTicks(startMs: number, endMs: number, maxTicks = 5): DateTick[] {
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return [];
  const span = endMs - startMs;
  const days = span / MS_DAY;

  if (days > 120) {
    const first = new Date(startMs);
    first.setUTCDate(1);
    first.setUTCHours(0, 0, 0, 0);
    if (first.getTime() < startMs) first.setUTCMonth(first.getUTCMonth() + 1);
    const months: number[] = [];
    for (const d = new Date(first); d.getTime() <= endMs; d.setUTCMonth(d.getUTCMonth() + 1)) {
      months.push(d.getTime());
    }
    const stride = Math.max(1, Math.ceil(months.length / maxTicks));
    const out: DateTick[] = [];
    for (let i = 0; i < months.length; i += stride) {
      out.push({ frac: (months[i] - startMs) / span, label: fmt(months[i], { month: "short" }) });
    }
    return out;
  }

  const n = Math.min(maxTicks, Math.max(2, Math.round(days / (days <= 14 ? 3 : 14)) + 1));
  const out: DateTick[] = [];
  for (let i = 0; i < n; i++) {
    const frac = i / (n - 1);
    out.push({ frac, label: fmt(startMs + frac * span, { day: "numeric", month: "short" }) });
  }
  return out;
}

// Parse a [start, end] ISO pair into epoch ms; null when either side is unusable
// so callers can conditionally render a dated axis.
export function dateDomainMs(domain?: [string, string]): [number, number] | null {
  if (!domain) return null;
  const a = Date.parse(domain[0]);
  const b = Date.parse(domain[1]);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return null;
  return [a, b];
}
