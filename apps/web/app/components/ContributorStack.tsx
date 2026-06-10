// Contributor stack (the locked chart vocabulary's replacement for donuts):
// signed horizontal bars showing what pushed today's recovery score, fed by
// the recovery_score finding's structured_data.contributors. Server-rendered.

export type Contributor = {
  label: string;
  // Signed percentage vs baseline (e.g. -18 = 18% below baseline) or an
  // absolute deviation; `unit` controls the printed suffix.
  value: number;
  unit: string;
  // Whether a positive value is good for this signal (HRV up = good,
  // resting HR up = bad) — drives the bar colour honestly.
  positiveIsGood: boolean;
};

const BAR_MAX_PCT = 40; // |value| that fills the whole half-bar

export function ContributorStack({ contributors }: { contributors: Contributor[] }) {
  const rows = contributors.filter((c) => Number.isFinite(c.value));
  if (rows.length === 0) return null;
  return (
    <ul className="contrib-stack" aria-label="Score contributors">
      {rows.map((c) => {
        const widthPct = Math.min(100, (Math.abs(c.value) / BAR_MAX_PCT) * 100);
        const good = c.positiveIsGood ? c.value >= 0 : c.value <= 0;
        return (
          <li key={c.label} className="contrib-row">
            <span className="contrib-label">{c.label}</span>
            <span className="contrib-track">
              <span
                className={`contrib-bar ${good ? "good" : "bad"} ${c.value < 0 ? "neg" : "pos"}`}
                style={{ width: `${widthPct / 2}%` }}
              />
            </span>
            <span className={`contrib-value mono ${good ? "up" : "down"}`}>
              {c.value > 0 ? "+" : ""}
              {Number(c.value.toFixed(1))}
              {c.unit}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
