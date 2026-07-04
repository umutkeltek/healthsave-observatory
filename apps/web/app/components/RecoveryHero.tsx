import { BaselineRibbon } from "./BaselineRibbon";
import { type Contributor, ContributorStack } from "./ContributorStack";
import { CountUp } from "./CountUp";

const STATES = [
  { min: 75, label: "Prime", cls: "state-prime", title: "Prime today" },
  { min: 60, label: "Steady", cls: "state-steady", title: "Steady today" },
  { min: 45, label: "Caution", cls: "state-caution", title: "Worth watching" },
  { min: 0, label: "Suppressed", cls: "state-suppressed", title: "Go easier today" },
] as const;

function stateFor(score: number) {
  return STATES.find((s) => score >= s.min) ?? STATES[STATES.length - 1];
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

export function RecoveryHero({
  freshness,
  score,
  summary,
  ribbon,
  live,
  contributors = [],
  highlights = [],
}: {
  freshness: string;
  score: number | null;
  summary: string;
  ribbon: HeroRibbon | null;
  live?: boolean;
  contributors?: Contributor[];
  highlights?: TodayHighlight[];
}) {
  const state = score !== null ? stateFor(score) : null;

  return (
    <section className={`hero today-hero ${state ? `hero-${state.cls}` : ""}`}>
      <div className="today-hero-main">
        <div className="today-status">
          <div className="hero-eyebrow">Today</div>
          <div className="today-scoreline">
            {score !== null && state ? (
              <>
                <span className="recovery-score">
                  <CountUp value={score} />
                </span>
                <span className={`recovery-state ${state.cls}`}>{state.label}</span>
              </>
            ) : (
              <span className="recovery-state state-caution">Building</span>
            )}
          </div>
          <h2>{state?.title ?? "Building your baseline"}</h2>
          <p>{summary}</p>
        </div>

        <div className="today-glance" aria-label="Today at a glance">
          <div className="today-glance-head">
            <span>At a glance</span>
            <strong>{live ? "Fresh" : "Check sync"}</strong>
          </div>
          <div className="today-glance-grid">
            {highlights.map((item) => (
              <div key={item.label} className={`today-glance-item ${item.tone === "watch" ? "watch" : ""}`}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <em>{item.hint}</em>
              </div>
            ))}
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
