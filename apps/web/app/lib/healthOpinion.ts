// The Observatory's point of view — opinionated, grounded, never diagnostic.
//
// Grounded in docs/healthResearch/ (sensor epistemics + multi-source
// reconciliation, fully cited there). Two hard lines carried verbatim from that
// research into this surface:
//   1. Never synthesize consensus. "When sources conflict materially, do not
//      silently average them" — show the conflict, keep both, and narrate from
//      the highest-confidence source. The gap is the signal, not a blended number.
//      Precedence is deterministic: prefer the more direct measurement modality,
//      then the more validated device class, then the more internally consistent
//      source.
//   2. Sensors measure physics, not the label. "Heart rate", "sleep stage" and
//      "HRV" are downstream inferences. We state each source's modality and the
//      confidence it earns, and never present an inference as ground truth.

import type { CoverageDomain } from "./provenance";

export type Confidence = "high" | "medium" | "low";

export type SourceReliability = {
  tag: string; // short visible modality tag
  best: string; // what this source is most trustworthy for
  confidence: Confidence; // confidence its primary signals earn
  note: string; // the grounded opinion (hover detail)
};

type ReliabilityRule = SourceReliability & { match: RegExp };

// Keyed off the source display name / plugin id; first match wins. The opinions
// are about MODALITY and VALIDATION, never about the body.
const RULES: ReliabilityRule[] = [
  {
    match: /chest|polar|strap|h10/i,
    tag: "chest · ECG",
    best: "workout HR · rhythm",
    confidence: "high",
    note: "Electrode-based — the gold standard for workout heart rate and rhythm. When it and a wrist source both report, the strap outranks wrist optics; we keep both and narrate from this one.",
  },
  {
    match: /oura/i,
    tag: "ring · PPG",
    best: "overnight HRV · sleep · temperature",
    confidence: "high",
    note: "Ring PPG is well validated for overnight HRV and sleep, with temperature as a disclosed trend signal. It reports RMSSD-style HRV — not directly comparable to Apple's SDNN, so we trend it on its own track rather than blending vendors.",
  },
  {
    match: /whoop/i,
    tag: "strap · PPG",
    best: "overnight HRV · strain",
    confidence: "high",
    note: "Strap PPG is strong for overnight HRV. Its strain score ignores sleep, so we cross-check load against recovery. RMSSD-based HRV — not comparable to Apple SDNN; never averaged across vendors.",
  },
  {
    match: /apple|healthkit|health\s?save|watch/i,
    tag: "wrist · PPG",
    best: "resting trends · activity",
    confidence: "medium",
    note: "Wrist PPG: solid at rest (CCC ~0.91 vs ECG), weaker in motion. HRV is SDNN — read it for your own trend, not cross-vendor comparison. Sleep staging is ~probabilistic vs lab PSG; SpO2 carries known pigmentation bias. Trust direction over absolutes.",
  },
  {
    match: /garmin|body\s?battery/i,
    tag: "wrist · score",
    best: "steps · raw HR",
    confidence: "low",
    note: "Body Battery is a proprietary composite with no published independent validation of the score — we keep its raw signals (HR, steps) and ignore the composite.",
  },
  {
    match: /manual|entry|self/i,
    tag: "manual",
    best: "context only",
    confidence: "low",
    note: "Manually entered — lowest precedence in reconciliation. Kept as context; never used to overwrite a sensor reading without surfacing the disagreement.",
  },
];

const UNKNOWN: SourceReliability = {
  tag: "unverified",
  best: "raw signals",
  confidence: "low",
  note: "Reliability not yet characterised for this source — we keep its raw signals verbatim and don't infer beyond them.",
};

export function reliabilityFor(source: string): SourceReliability {
  return RULES.find((r) => r.match.test(source)) ?? UNKNOWN;
}

// Vendor family of a source — the axis along which device measurements diverge.
function family(source: string): string {
  const s = source.toLowerCase();
  if (/oura/.test(s)) return "oura";
  if (/whoop/.test(s)) return "whoop";
  if (/garmin/.test(s)) return "garmin";
  if (/apple|healthkit|health\s?save|watch|iphone/.test(s)) return "apple";
  return "other";
}

export type Comparability = { comparable: boolean; warn: boolean; caveat: string | null };

// Whether two (or more) sources can be compared for a metric — grounded in the
// research's reconciliation rule: keep both, never average, and surface what the
// science says about each device. The canonical incomparable case is HRV across
// vendors (Apple SDNN vs Whoop/Oura RMSSD). We never hard-block — we warn loudly
// and still render both readings verbatim.
export function comparability(metricId: string, sources: string[]): Comparability {
  const families = [...new Set(sources.map(family))];
  const crossVendor = families.length > 1;
  if (!crossVendor) {
    return { comparable: true, warn: false, caveat: null };
  }
  if (/hrv/.test(metricId)) {
    return {
      comparable: false,
      warn: true,
      caveat:
        "Apple reports HRV as SDNN; Whoop and Oura report RMSSD — different definitions that are not directly comparable. Shown side by side, never merged.",
    };
  }
  return {
    comparable: true,
    warn: false,
    caveat:
      "Cross-source comparison — these devices measure differently (wrist PPG vs ring/strap/ECG). Read the gap as provenance, not a verdict: both kept, never averaged.",
  };
}

export type Verdict = {
  state: "prime" | "steady" | "caution" | "suppressed";
  label: string;
  line: string;
};

// An opinion on your ingestion health, derived purely from freshness (a count
// over your own streams — never a merged consensus value). It takes a stance and
// tells you what to do, grounded in the research's baseline rule: a usable
// baseline needs ~5 of the last 7 valid nights, so a source going dark gaps your
// overnight signals first.
export function coverageVerdict(domains: CoverageDomain[]): Verdict {
  if (domains.length === 0) {
    return {
      state: "caution",
      label: "No sources",
      line: "Connect a source to start building the baselines every finding is measured against (≈5 of 7 valid nights).",
    };
  }
  const stale = domains.filter((d) => d.tone === "warn");
  if (stale.length === 0) {
    return {
      state: "steady",
      label: "Solid",
      line: "Every source is syncing — your 5-of-7-night baselines hold, so findings stay trustworthy.",
    };
  }
  const lead = stale[0];
  const gaps = reliabilityFor(lead.label).best;
  const more = stale.length > 1 ? ` (+${stale.length - 1} more)` : "";
  const degraded = stale.length >= 2;
  return {
    state: degraded ? "suppressed" : "caution",
    label: degraded ? "Degraded" : "Watch",
    line: `${lead.label}${more} has gone stale — ${gaps} gaps first. Reconnect before it slips below the 5-of-7 valid nights your baselines need.`,
  };
}
