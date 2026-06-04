import { BaselineRibbon } from "./BaselineRibbon";

// Score → state label, using the same bands the product narrates by. The score
// itself is the backend's open formula (analysis/statistical/scoring.py); we
// only translate it to a word + colour.
const STATES = [
  { min: 75, label: "Prime", cls: "state-prime" },
  { min: 60, label: "Steady", cls: "state-steady" },
  { min: 45, label: "Caution", cls: "state-caution" },
  { min: 0, label: "Suppressed", cls: "state-suppressed" },
] as const;

function stateFor(score: number) {
  return STATES.find((s) => score >= s.min) ?? STATES[STATES.length - 1];
}

export type HeroRibbon = {
  values: number[];
  band?: [number, number];
  axis?: [string, string];
};

// The Today centrepiece. Degrades honestly: the recovery number shows only when
// the engine has computed one; otherwise the briefing headline leads and the
// ribbon still anchors the card with a real signal.
export function RecoveryHero({
  freshness,
  score,
  headline,
  ribbon,
}: {
  freshness: string;
  score: number | null;
  headline: string;
  ribbon: HeroRibbon | null;
}) {
  const state = score !== null ? stateFor(score) : null;

  return (
    <section className="hero col-8">
      <div className="hero-eyebrow">Today · last reading {freshness}</div>

      {score !== null && state && (
        <div className="recovery">
          <div className="recovery-score">{score}</div>
          <div className={`recovery-state ${state.cls}`}>{state.label}</div>
        </div>
      )}

      <p className="recovery-line" style={score === null ? { marginTop: 6, fontSize: 17 } : undefined}>
        {headline}
      </p>

      {ribbon && ribbon.values.length >= 2 && (
        <BaselineRibbon values={ribbon.values} band={ribbon.band} axis={ribbon.axis} />
      )}
    </section>
  );
}
