import type { MetricSeries, SeriesPoint } from "../lib/api";
import { formatValue } from "../lib/format";

// Card summarising walking load: highest-fidelity signals the device exposes.
// Each stat is a real series point with a meaningful aggregation, never an
// invented number. Empty sections collapse to an honest "no data" line.
type NamedSeries = { name: string; unit: string | null; series: MetricSeries | null };

function latest(points: SeriesPoint[]): SeriesPoint | null {
  if (points.length === 0) return null;
  return [...points].sort((a, b) => (a.t < b.t ? 1 : a.t > b.t ? -1 : 0))[0];
}

function fmt(value: number | null, unit: string | null): string {
  return formatValue(value, unit);
}

function Stat({ name, unit, series }: NamedSeries) {
  const last = latest(series?.points ?? []);
  const value = last && last.value !== null ? last.value : null;
  const ago = last ? last.t : null;
  // Prefer the backend's canonical unit; the prop is the fallback so the card
  // can't silently lie if a unit string ever changes upstream.
  const unitFromSeries = series?.metric.canonical_unit ?? unit;
  return (
    <div className="mobility-stat">
      <span className="mobility-stat-label">{name}</span>
      <span className="mobility-stat-value big mono">{fmt(value, unitFromSeries)}</span>
      <span className="mobility-stat-meta meta">
        {ago ? new Date(ago).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "no data yet"}
      </span>
    </div>
  );
}

export function MobilityCard({ seriesByMetric }: { seriesByMetric: Record<string, MetricSeries | null> }) {
  const totalPoints = Object.values(seriesByMetric).reduce(
    (n, s) => n + (s?.points.filter((p) => p.value !== null).length ?? 0),
    0,
  );
  if (totalPoints === 0) {
    return (
      <article className="card">
        <h2>Walking</h2>
        <p className="empty">
          No walking data yet. Apple Watch Full Export and supported devices can stream speed, step length,
          asymmetry, and walking heart rate into this card.
        </p>
      </article>
    );
  }

  return (
    <article className="card">
      <h2>Walking</h2>
      <div className="mobility-stats">
        <Stat name="Walking HR" unit="bpm" series={seriesByMetric["vital.walking_heart_rate_average"] ?? null} />
        <Stat name="Speed" unit="m/s" series={seriesByMetric["mobility.walking_speed"] ?? null} />
        <Stat name="Step length" unit="cm" series={seriesByMetric["mobility.walking_step_length"] ?? null} />
        <Stat name="Asymmetry" unit="%" series={seriesByMetric["mobility.walking_asymmetry"] ?? null} />
      </div>
    </article>
  );
}
