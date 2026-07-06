// Shared chart math - the single home for the scale/quantile helpers that
// were previously duplicated in BaselineRibbon and the Library detail page.
// Pure functions, unit-tested in scale.test.ts.

export function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const next = sorted[base + 1];
  return next !== undefined ? sorted[base] + rest * (next - sorted[base]) : sorted[base];
}

export function extent(values: number[]): [number, number] {
  if (values.length === 0) return [0, 0]; // never leak ±Infinity into scales
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return [min, max];
}

// Map a domain value onto an output range (no clamping - callers pad domains).
export function linearScale(
  domain: [number, number],
  range: [number, number],
): (value: number) => number {
  const span = domain[1] - domain[0] || 1;
  return (value) => range[0] + ((value - domain[0]) / span) * (range[1] - range[0]);
}

// Round-number axis ticks covering [min, max] (1/2/5 ladder). `count` is the
// target number of INTERVALS: the raw step (span / count) is rounded UP to the
// next nice number, so the tick count never exceeds count + 1. (Rounding the
// raw step DOWN — the old behaviour — could more than double the tick count:
// a span-18 range at count 4 gives raw step 4.5, which floored to 2 yielded
// ten cramped ticks; rounding up to 5 yields four.)
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const rawStep = (max - min) / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude; // in [1, 10)
  const step = (residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 5 ? 5 : 10) * magnitude;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step / 1e6; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

// A robust y-domain for a noisy trace: the p2-p98 quantile band of the series
// (so a handful of spikes can't flatten the rest into a hairline), always
// widened to contain the baseline band bounds when they are supplied. Callers
// clamp their trace points into this domain so outliers pin at the edge instead
// of stretching the scale. Degenerate (constant) and empty inputs still return
// a finite, positive-width domain.
export function robustDomain(values: number[], bandLo?: number, bandHi?: number): [number, number] {
  const bounds: number[] = [];
  if (Number.isFinite(bandLo)) bounds.push(bandLo as number);
  if (Number.isFinite(bandHi)) bounds.push(bandHi as number);
  const finite = values.filter((v) => Number.isFinite(v));

  let lo: number;
  let hi: number;
  if (finite.length === 0) {
    if (bounds.length === 0) return [0, 1];
    lo = Math.min(...bounds);
    hi = Math.max(...bounds);
  } else {
    const sorted = [...finite].sort((a, b) => a - b);
    lo = quantile(sorted, 0.02);
    hi = quantile(sorted, 0.98);
    for (const b of bounds) {
      if (b < lo) lo = b;
      if (b > hi) hi = b;
    }
  }

  if (hi > lo) return [lo, hi];
  // Degenerate: pad symmetrically so the scale keeps a positive width.
  const center = lo;
  const pad = Math.abs(center) > 1e-9 ? Math.abs(center) * 0.05 : 0.5;
  return [center - pad, center + pad];
}
