import type { CardEffectSize, Finding, FindingCard } from "./api";

export type FindingGroupId = "needs-attention" | "improving" | "watching" | "background";

export type FindingDisplayGroup = {
  id: FindingGroupId;
  title: string;
  description: string;
  findings: Finding[];
};

export type FindingDisplayItem =
  | { kind: "finding"; key: string; finding: Finding; count: 1 }
  | {
      kind: "cluster";
      key: string;
      title: string;
      summary: string;
      proof: string;
      count: number;
      findings: Finding[];
    };

const GROUPS: Omit<FindingDisplayGroup, "findings">[] = [
  {
    id: "needs-attention",
    title: "Needs attention",
    description: "Signals outside usual range or marked high severity.",
  },
  {
    id: "improving",
    title: "Improving",
    description: "Positive movement or recovery context worth noticing.",
  },
  {
    id: "watching",
    title: "Watching",
    description: "Changes real enough to track, but not urgent.",
  },
  {
    id: "background",
    title: "Background evidence",
    description: "Supporting summaries and lower-priority proof.",
  },
];

const METRIC_TITLES: Record<string, string> = {
  "activity.active_energy": "Active energy",
  "activity.steps": "Steps",
  recovery: "Recovery score",
  "sleep.stage": "Sleep stages",
  "vital.heart_rate": "Heart rate",
  "vital.hrv_sdnn": "Heart rate variability",
  "vital.respiratory_rate": "Respiratory rate",
  "vital.resting_heart_rate": "Resting heart rate",
  "vital.spo2": "Blood oxygen",
  "vital.walking_heart_rate_average": "Walking heart rate",
};

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function titleFromId(id: string): string {
  const last = id.includes(".") ? (id.split(".").at(-1) ?? id) : id;
  return last
    .split("_")
    .filter(Boolean)
    .map((part) => (part[0]?.toUpperCase() ?? "") + part.slice(1))
    .join(" ");
}

export function userFindingTitle(finding: Finding): string {
  if (finding.finding_type === "recovery_score") return "Recovery score";
  if (finding.metric && METRIC_TITLES[finding.metric]) return METRIC_TITLES[finding.metric];
  if (finding.metric) return titleFromId(finding.metric);
  return "Health signal";
}

export function findingGroupId(finding: Finding): FindingGroupId {
  const type = finding.finding_type ?? "";
  const severity = (finding.severity ?? "").toLowerCase();
  const direction = textValue(finding.structured_data?.direction)?.toLowerCase();
  const delta = numberValue(finding.structured_data?.delta_pct_vs_baseline);
  const score = numberValue(finding.structured_data?.score);

  if (type === "anomaly" || severity === "warning" || severity === "critical" || severity === "high") {
    return "needs-attention";
  }

  if (type === "recovery_score") return score !== null && score < 55 ? "watching" : "improving";

  if (type === "trend") {
    if (direction === "up" || (delta !== null && delta > 0)) return "improving";
    return "watching";
  }

  if (type === "correlation") return "watching";
  return "background";
}

export function userFindingSummary(finding: Finding): string {
  const data = finding.structured_data ?? {};
  const type = finding.finding_type ?? "";

  if (type === "anomaly") {
    const direction = textValue(data.direction) === "down" ? "below" : "above";
    const magnitude = numberValue(data.magnitude);
    return `Outside your usual range${magnitude !== null ? ` by ${Math.abs(magnitude).toFixed(1)} z` : ""}, ${direction} baseline.`;
  }

  if (type === "trend") {
    const direction = textValue(data.direction);
    const days = numberValue(data.period_days);
    return `${direction === "down" ? "Downward" : "Upward"} movement${days ? ` over ${Math.round(days)} days` : ""}.`;
  }

  if (type === "correlation") {
    const coefficient = numberValue(data.coefficient);
    return `Moves with another signal${coefficient !== null ? `, r=${coefficient.toFixed(2)}` : ""}.`;
  }

  if (type === "recovery_score") {
    const score = numberValue(data.score);
    return score !== null ? `Current recovery score ${Math.round(score)}.` : "Recovery context from recent signals.";
  }

  const avg = numberValue(data.avg);
  const delta = numberValue(data.delta_pct_vs_baseline);
  if (avg !== null || delta !== null) {
    return [
      avg !== null ? `Average ${avg.toFixed(1)}` : null,
      delta !== null ? `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}% vs baseline` : null,
    ]
      .filter(Boolean)
      .join(", ");
  }

  return "Computed from local observations.";
}

export function findingProofLine(finding: Finding): string {
  const type = finding.finding_type ?? "";
  const data = finding.structured_data ?? {};

  if (type === "anomaly") return `${finding.severity ?? "Flagged"} severity, deviated from baseline.`;

  if (type === "trend") {
    const p = numberValue(data.p_value);
    return p !== null ? `Statistically meaningful trend, p=${p.toFixed(3)}.` : "Sustained multi-day direction.";
  }

  if (type === "correlation") {
    const p = numberValue(data.p_value);
    return p !== null ? `Cross-signal relationship, p=${p.toFixed(3)}.` : "Cross-signal relationship.";
  }

  if (type === "recovery_score") return "Derived from the recovery scoring engine.";
  return "Period rollup against baseline.";
}

function dateValue(finding: Finding): number {
  const value = finding.created_at ? new Date(finding.created_at).getTime() : NaN;
  return Number.isFinite(value) ? value : 0;
}

function scoreRange(findings: Finding[]): { latest: number | null; min: number | null; max: number | null } {
  const ordered = [...findings].sort((a, b) => dateValue(b) - dateValue(a));
  const scores = findings
    .map((finding) => numberValue(finding.structured_data?.score))
    .filter((score): score is number => score !== null);

  return {
    latest: numberValue(ordered[0]?.structured_data?.score),
    min: scores.length ? Math.min(...scores) : null,
    max: scores.length ? Math.max(...scores) : null,
  };
}

export function displayItemsForFindings(findings: Finding[]): FindingDisplayItem[] {
  const recovery = findings.filter((finding) => finding.finding_type === "recovery_score");

  if (recovery.length < 5) {
    return findings.map((finding) => ({
      kind: "finding",
      key: `finding-${finding.id}`,
      finding,
      count: 1,
    }));
  }

  const recoveryIds = new Set(recovery.map((finding) => finding.id));
  const { latest, min, max } = scoreRange(recovery);
  const range =
    min !== null && max !== null
      ? `Range ${Math.round(min)}-${Math.round(max)}.`
      : "Individual snapshots retained.";
  const summary =
    latest !== null
      ? `${recovery.length} recovery checks. Latest score ${Math.round(latest)}. ${range}`
      : `${recovery.length} recovery checks. ${range}`;
  const cluster: FindingDisplayItem = {
    kind: "cluster",
    key: "cluster-recovery-score",
    title: "Recovery score history",
    summary,
    proof: "Derived from the recovery scoring engine. Open details to inspect each snapshot.",
    count: recovery.length,
    findings: recovery,
  };

  const items: FindingDisplayItem[] = [];
  let inserted = false;

  for (const finding of findings) {
    if (!recoveryIds.has(finding.id)) {
      items.push({ kind: "finding", key: `finding-${finding.id}`, finding, count: 1 });
      continue;
    }

    if (!inserted) {
      items.push(cluster);
      inserted = true;
    }
  }

  return items;
}

export function groupFindingsForDisplay(findings: Finding[]): FindingDisplayGroup[] {
  const map = new Map<FindingGroupId, Finding[]>();
  for (const group of GROUPS) map.set(group.id, []);
  for (const finding of findings) map.get(findingGroupId(finding))?.push(finding);
  return GROUPS.map((group) => ({ ...group, findings: map.get(group.id) ?? [] }));
}

// ── FindingCard presentation (the ONE card grammar) ───────────────────
// Pure mapping from a computed FindingCard to its rendered chips + labels. The
// component is a thin shell over these; tests pin the honest formatting here.

// Tone maps onto the semantic token classes (fc-chip-*). Direction is NOT toned
// good/bad - up HRV is good, up resting-HR is not; the card never colors a
// change as a verdict. Only confidence + coverage carry a quality tone.
export type CardChipTone = "good" | "warn" | "neutral" | "muted";

export type CardChip = {
  key: string;
  label: string;
  value: string;
  tone: CardChipTone;
};

const DIRECTION_ARROW: Record<string, string> = { up: "↑", down: "↓", flat: "→" };

const EFFECT_SYMBOL: Record<string, string> = {
  z_score: "z",
  spearman_rho: "ρ",
  pearson_r: "r",
  slope_per_day: "slope",
  cohens_d: "d",
};

function fmtNum(value: number, digits = 1): string {
  return Number(value.toFixed(digits)).toString();
}

// "z = 2.1", "ρ = 0.62", "slope 0.34/day" - method-tagged so a coefficient is
// never mistaken for a standardized difference.
export function effectSizeText(effect: CardEffectSize): string | null {
  if (effect.value == null) return null;
  const kind = effect.kind ?? "";
  const symbol = EFFECT_SYMBOL[kind];
  if (kind === "slope_per_day") return `slope ${fmtNum(effect.value, 2)}/day`;
  if (symbol) return `${symbol} = ${fmtNum(effect.value, 2)}`;
  return fmtNum(effect.value, 2);
}

export function confidenceTone(confidence: FindingCard["confidence"]): CardChipTone {
  if (confidence === "high") return "good";
  if (confidence === "medium") return "neutral";
  return "muted";
}

// The chip row: delta, effect size, coverage, confidence, window-n - each only
// when the computed card carries it (a thin card renders fewer chips honestly).
export function findingCardChips(card: FindingCard): CardChip[] {
  const chips: CardChip[] = [];

  const delta = card.delta;
  if (delta && (delta.pct != null || delta.absolute != null)) {
    const arrow = delta.direction ? `${DIRECTION_ARROW[delta.direction] ?? ""} ` : "";
    const value =
      delta.pct != null
        ? `${arrow}${delta.pct >= 0 ? "+" : ""}${fmtNum(delta.pct)}%`
        : `${arrow}${delta.absolute! >= 0 ? "+" : ""}${fmtNum(delta.absolute!, 2)}${delta.unit ? ` ${delta.unit}` : ""}`;
    chips.push({ key: "delta", label: "vs baseline", value, tone: "neutral" });
  }

  if (card.effect_size) {
    const text = effectSizeText(card.effect_size);
    if (text) {
      const label = card.effect_size.label ? `${card.effect_size.label} effect` : "effect size";
      chips.push({ key: "effect", label, value: text, tone: "neutral" });
    }
    if (card.effect_size.p_value != null) {
      chips.push({
        key: "p",
        label: "significance",
        value: `p = ${fmtNum(card.effect_size.p_value, 3)}`,
        tone: "neutral",
      });
    }
  }

  if (card.current_window?.n != null) {
    chips.push({
      key: "n",
      label: "window",
      value: `n = ${card.current_window.n}`,
      tone: "neutral",
    });
  }

  const coverage = card.coverage;
  if (coverage && (coverage.is_sufficient != null || coverage.observation_count != null)) {
    const value =
      coverage.observation_count != null
        ? `${coverage.observation_count} obs`
        : coverage.is_sufficient
          ? "sufficient"
          : "thin";
    chips.push({
      key: "coverage",
      label: "coverage",
      value,
      tone: coverage.is_sufficient === false ? "warn" : "good",
    });
  }

  if (card.confidence) {
    chips.push({
      key: "confidence",
      label: "confidence",
      value: card.confidence,
      tone: confidenceTone(card.confidence),
    });
  }

  return chips;
}

// A card whose metric is a correlation pair ("a~b") has no single series to
// plot; the component skips the proof figure instead of drawing a wrong one.
export function cardMetricIsPlottable(metric: string): boolean {
  return Boolean(metric) && !metric.includes("~");
}
