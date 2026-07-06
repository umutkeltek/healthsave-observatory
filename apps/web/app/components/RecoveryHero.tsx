import { BaselineRibbon } from "./BaselineRibbon";
import { BodyDial, type DialTone } from "./BodyDial";
import { type Contributor, ContributorStack } from "./ContributorStack";

const STATES = [
  { min: 75, label: "Prime", cls: "state-prime", tone: "good" },
  { min: 60, label: "Steady", cls: "state-steady", tone: "good" },
  { min: 45, label: "Caution", cls: "state-caution", tone: "warn" },
  { min: 0, label: "Suppressed", cls: "state-suppressed", tone: "muted" },
] as const;

function stateFor(score: number) {
  return STATES.find((s) => score >= s.min) ?? STATES[STATES.length - 1];
}

// The lede leads with ONE finding sentence (h1), the rest of the deterministic
// summary follows as a muted dek. Pure string reshaping — invents nothing.
function splitSummary(summary: string): [string, string] {
  const match = summary.match(/^(.*?[.!?])\s+(.+)$/s);
  return match ? [match[1], match[2]] : [summary, ""];
}

export type HeroRibbon = {
  values: number[];
  band?: [number, number];
  axis?: [string, string];
};

export type TodayHighlight = {
  label: string;
  value: string;
  hint: string;
  tone?: "good" | "watch";
};

// A byline atom: `{lead}<b>{strong}</b>{trail}`. Built only from data the hero
// already receives (baseline window, ready-signal count, sync freshness) —
// never an invented number.
export type BylineItem = {
  lead?: string;
  strong: string;
  trail?: string;
};

export function RecoveryHero({
  freshness,
  score,
  summary,
  ribbon,
  live,
  contributors = [],
  byline = [],
  deltaPct = null,
}: {
  freshness: string;
  score: number | null;
  summary: string;
  ribbon: HeroRibbon | null;
  live?: boolean;
  contributors?: Contributor[];
  byline?: BylineItem[];
  deltaPct?: number | null;
}) {
  const state = score !== null ? stateFor(score) : null;
  const tone: DialTone = state ? state.tone : "muted";
  const [headline, dek] = splitSummary(summary);
  const hasDelta = typeof deltaPct === "number" && Number.isFinite(deltaPct);

  return (
    <section className={`hero today-hero ${state ? `hero-${state.cls}` : ""}`}>
      <div className="today-hero-main">
        <div className="hero-lede">
          <div className="hero-eyebrow">Today&rsquo;s lead finding</div>
          <h1 className="hero-lede-head">{headline}</h1>
          {dek && <p className="hero-lede-dek">{dek}</p>}
          {byline.length > 0 && (
            <div className="hero-byline mono">
              {byline.map((item, i) => (
                <span key={i}>
                  {item.lead}
                  <b>{item.strong}</b>
                  {item.trail}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className={`hero-instrument dial-tone-${tone}`}>
          <BodyDial score={score} tone={tone} caption="Recovery" />
          <div className="hero-instrument-meta">
            {state ? (
              <span className="hero-chip">{state.label}</span>
            ) : (
              <span className="hero-chip">Building</span>
            )}
            {hasDelta && (
              <span className="hero-delta mono">
                {deltaPct! >= 0 ? "+" : "−"}
                {Math.abs(deltaPct!).toFixed(0)}% vs baseline
              </span>
            )}
          </div>
        </div>
      </div>

      {ribbon && ribbon.values.length >= 2 && (
        <div className="today-ribbon">
          <div className="today-ribbon-head">
            <span>HRV baseline</span>
            <em>last reading {freshness}</em>
          </div>
          <BaselineRibbon values={ribbon.values} band={ribbon.band} axis={ribbon.axis} live={live} />
        </div>
      )}

      {contributors.length > 0 && (
        <div className="today-contributors">
          <ContributorStack contributors={contributors} />
        </div>
      )}
    </section>
  );
}
