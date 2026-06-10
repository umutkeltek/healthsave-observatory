// Shared chart math — the single home for the scale/quantile helpers that
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
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return [min, max];
}

// Map a domain value onto an output range (no clamping — callers pad domains).
export function linearScale(
  domain: [number, number],
  range: [number, number],
): (value: number) => number {
  const span = domain[1] - domain[0] || 1;
  return (value) => range[0] + ((value - domain[0]) / span) * (range[1] - range[0]);
}

// Round-number axis ticks covering [min, max] (1/2/5 ladder).
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const rawStep = (max - min) / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const step = (residual >= 5 ? 5 : residual >= 2 ? 2 : 1) * magnitude;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step / 1e6; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}
