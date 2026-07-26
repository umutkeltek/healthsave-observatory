export type TimedPoint = { t: string; value: number };

export type TimedSegment = TimedPoint[];

function validPoint(point: TimedPoint): boolean {
  return Number.isFinite(Date.parse(point.t)) && Number.isFinite(point.value);
}

// Split a timestamped series at unusually large missing intervals. The threshold
// is relative to the series' typical cadence, with a 36-hour floor so daily
// signals tolerate ordinary clock/DST movement without bridging true missing days.
export function timedSegments(points: TimedPoint[]): TimedSegment[] {
  const sorted = points.filter(validPoint).slice().sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
  if (sorted.length < 2) return sorted.length ? [sorted] : [];

  const gaps = sorted
    .slice(1)
    .map((point, index) => Date.parse(point.t) - Date.parse(sorted[index].t))
    .filter((gap) => gap > 0)
    .sort((a, b) => a - b);
  const medianGap = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;
  const threshold = Math.max(36 * 3_600_000, medianGap * 3);

  const segments: TimedSegment[] = [[sorted[0]]];
  for (let index = 1; index < sorted.length; index += 1) {
    const point = sorted[index];
    const previous = sorted[index - 1];
    if (Date.parse(point.t) - Date.parse(previous.t) > threshold) segments.push([]);
    segments[segments.length - 1].push(point);
  }
  return segments;
}

export function timedDomain(series: { points: TimedPoint[] }[]): [string, string] | undefined {
  const times = series.flatMap((item) => item.points.map((point) => Date.parse(point.t))).filter(Number.isFinite);
  if (times.length < 2) return undefined;
  const start = Math.min(...times);
  const end = Math.max(...times);
  return end > start ? [new Date(start).toISOString(), new Date(end).toISOString()] : undefined;
}
