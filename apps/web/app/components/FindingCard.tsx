// The FindingCard - the ONE card grammar the product speaks: a plain-language
// claim as the headline, PROOF IN PLACE (the finding's metric drawn against its
// own baseline via BaselineRibbon), the computed delta/effect/coverage/
// confidence as chips, limitations + confounders behind a drilldown, and the
// next-question CTA (promotable to an experiment when the card carries a
// candidate). Every value is Brain-1 computed content; nothing here is narrated.
//
// Split in two: the async `FindingCard` fetches the proof series server-side
// (safe* degradation - a missing series drops the figure, never the card); the
// pure `FindingCardView` renders from props so it unit-tests and renders
// standalone.

import type { Finding, FindingCard as FindingCardModel, MetricSeries } from "../lib/api";
import {
  cardMetricIsPlottable,
  findingCardChips,
  userFindingTitle,
} from "../lib/findingPresentation";
import { experimentHref } from "../lib/experimentPrefill";
import { BaselineRibbon } from "./BaselineRibbon";

// The proof-figure window. Exported so FindingsSections can resolve the series
// for EVERY card in one batched /api/v2/series call (see the pure FindingCard
// below) instead of one uncached fetch per card.
export const PROOF_RANGE = "30d";

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// A per-card label so N proof ribbons are distinguishable to assistive tech
// (the ribbon's default label is identical for every figure on the page).
function proofAriaLabel(card: FindingCardModel): string {
  const claim = card.claim.length > 90 ? `${card.claim.slice(0, 89).trimEnd()}…` : card.claim;
  return `${card.metric} — proof for: ${claim}`;
}

type ViewProps = {
  card: FindingCardModel;
  // Proof series (resolved by the async wrapper; omit to render claim-only).
  values?: number[] | null;
  hoverLabels?: string[];
  unit?: string | null;
  live?: boolean;
  createdAt?: string | null;
};

export function FindingCardView({
  card,
  values,
  hoverLabels,
  unit,
  live,
  createdAt,
}: ViewProps) {
  const chips = findingCardChips(card);
  const plottable = values && values.length >= 2 && cardMetricIsPlottable(card.metric);
  const nq = card.next_question;
  const href = experimentHref(nq?.experiment_candidate ?? null);
  const drilldown = card.limitations.length > 0 || card.confounders.length > 0;

  return (
    <article className="card fc">
      <header className="fc-head">
        <span className="fc-metric">{userFindingTitle({ ...FALLBACK_FINDING, metric: card.metric, finding_type: card.finding_type })}</span>
        {createdAt && <span className="fc-when mono">{fmtDate(createdAt)}</span>}
      </header>

      <h3 className="fc-claim">{card.claim}</h3>

      {plottable ? (
        <div className="fc-fig">
          <BaselineRibbon
            values={values as number[]}
            anomalies={[]}
            axis={[card.baseline_window?.label ?? "baseline", card.current_window?.label ?? "now"]}
            hoverLabels={hoverLabels}
            unit={unit}
            live={live}
            ariaLabel={proofAriaLabel(card)}
          />
        </div>
      ) : (
        <p className="fc-nofig">
          {cardMetricIsPlottable(card.metric)
            ? "Proof series not available for this window."
            : "A relationship between two signals — see the pair on Relationships."}
        </p>
      )}

      {chips.length > 0 && (
        <ul className="fc-chips">
          {chips.map((chip) => (
            <li key={chip.key} className={`fc-chip fc-chip-${chip.tone}`}>
              <span className="fc-chip-k">{chip.label}</span>
              <span className="fc-chip-v mono">{chip.value}</span>
            </li>
          ))}
        </ul>
      )}

      {drilldown && (
        <details className="fc-drill">
          <summary>Limitations &amp; confounders</summary>
          {card.confounders.length > 0 && (
            <ul className="fc-confounders">
              {card.confounders.map((c) => (
                <li key={`${c.kind}-${c.description}`}>
                  <span className="fc-confounder-kind">{c.kind.replace(/_/g, " ")}</span>
                  <span>{c.description}</span>
                </li>
              ))}
            </ul>
          )}
          {card.limitations.length > 0 && (
            <ul className="fc-limitations">
              {card.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          )}
        </details>
      )}

      {nq && (
        <div className="fc-next">
          <span className="fc-next-label">Next question</span>
          <p className="fc-next-prose">{nq.prose}</p>
          {href && (
            <a className="btn fc-next-cta" href={href}>
              Propose an experiment →
            </a>
          )}
        </div>
      )}
    </article>
  );
}

// userFindingTitle only reads metric + finding_type; the rest is filler so the
// FindingCardView can reuse the existing title mapping without a Finding row.
const FALLBACK_FINDING = {
  id: 0,
  metric: null,
  finding_type: null,
  severity: null,
  structured_data: {},
  created_at: null,
  card: null,
  schema_version: 0,
} satisfies Finding;

// Derive the proof-figure props from an ALREADY-resolved series (or null). The
// series is fetched once, in a batch, by the caller (FindingsSections) — this
// component no longer does its own fetch, so a page of cards costs one series
// request, not N. A missing series (unreachable backend, correlation-pair
// metric, or thin window) drops the figure only; the card still renders.
function proofFigureProps(card: FindingCardModel, series: MetricSeries | null) {
  if (!series || !cardMetricIsPlottable(card.metric)) {
    return { values: null as number[] | null, hoverLabels: undefined as string[] | undefined, unit: null as string | null, live: false };
  }
  const points = series.points.filter((p) => p.value !== null);
  const last = points.at(-1);
  return {
    values: points.map((p) => p.value as number),
    hoverLabels: points.map((p) => new Date(p.t).toLocaleDateString()),
    unit: series.metric.canonical_unit ?? points.find((p) => p.unit)?.unit ?? null,
    live: last ? Date.now() - new Date(last.t).getTime() < 24 * 3_600_000 : false,
  };
}

// Pure card: the caller resolves the proof series (batched) and passes it in.
export function FindingCard({ finding, series }: { finding: Finding; series: MetricSeries | null }) {
  const card = finding.card;
  if (!card) return null; // legacy findings render via EvidenceCard

  const { values, hoverLabels, unit, live } = proofFigureProps(card, series);

  return (
    <FindingCardView
      card={card}
      values={values}
      hoverLabels={hoverLabels}
      unit={unit}
      live={live}
      createdAt={finding.created_at}
    />
  );
}
