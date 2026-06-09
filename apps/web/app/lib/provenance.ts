// Provenance view-model — the join + derivations behind the Sources page.
//
// Pure (no I/O): the page fetches sources + streams from the v2 identity API
// (server/api/v2_identity.py) and hands them here to build display rows. The
// honesty rule the whole page is built on: we surface where each reading came
// from and how fresh it is — we never merge disagreeing sources into a single
// synthetic "truth".

import type { SourceView, StreamView } from "./api";
import { agoLabel } from "./load";

export type ProvenanceRow = {
  streamId: string; // full id (UUID for real rows) — shown on hover
  shortId: string; // compact monospace token for the table cell
  sourceName: string; // joined source.display_name (falls back to plugin id)
  origin: string; // the integration/plugin the stream arrived through
  hardware: string; // device_label — the physical emitter
  lastSync: string; // "12m ago" relative label
  freshness: number; // 0..1 — a view of recency, NOT a fabricated integrity score
  stale: boolean; // synced longer ago than the stale threshold
};

export type Divergence = {
  metric: string;
  context: string; // e.g. "Last Night" — rendered parenthetically
  readings: { source: string; value: string }[]; // every source kept verbatim
  resolution: string; // e.g. "Both Kept" — never a merged value
  stance?: string; // the Observatory's grounded opinion on the disagreement
  note?: string; // optional alignment caveat
  warn?: boolean; // amber treatment for a flagged divergence
};

export type CoverageDomain = { id: string; label: string; pct: number; tone: "ok" | "warn" };

export type Coverage = {
  headline: number; // mean of the per-source freshness bars shown
  total: number; // stream count behind the summary
  domains: CoverageDomain[];
};

// A stream is "stale" once it hasn't synced for a day. Tuned for human scanning,
// not a contract — it only drives colour, never a stored judgement.
const STALE_AFTER_MIN = 24 * 60;

function minutesAgo(iso: string | null | undefined): number {
  if (!iso) return Number.POSITIVE_INFINITY;
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 60000)) : Number.POSITIVE_INFINITY;
}

// Freshness as a 0..1 bar: full at sync, decaying to a floor by the stale
// threshold. It is a visualisation of last_seen_at — not a data-integrity claim.
export function freshness(iso: string | null | undefined): { value: number; stale: boolean } {
  const mins = minutesAgo(iso);
  if (!Number.isFinite(mins)) return { value: 0, stale: true };
  const stale = mins > STALE_AFTER_MIN;
  const value = mins <= 5 ? 1 : Math.max(0.18, 1 - (Math.min(mins, STALE_AFTER_MIN) / STALE_AFTER_MIN) * 0.82);
  return { value: Number(value.toFixed(3)), stale };
}

// Real stream ids are UUIDs; show the leading hex segment in monospace with the
// full id on hover. Fixture ids (already short) pass through unchanged.
export function shortId(id: string): string {
  const head = id.split("-")[0];
  return head.length >= 6 ? head.slice(0, 8) : id;
}

// Join streams → sources on plugin_id, newest sync first. The display_name is
// the human label for the integration; the plugin id is the honest fallback.
export function buildProvenanceRows(streams: StreamView[], sources: SourceView[]): ProvenanceRow[] {
  const nameByPlugin = new Map(sources.map((s) => [s.plugin_id, s.display_name ?? s.plugin_id]));
  return [...streams]
    .sort((a, b) => new Date(b.last_seen_at).getTime() - new Date(a.last_seen_at).getTime())
    .map((s) => {
      const f = freshness(s.last_seen_at);
      return {
        streamId: s.id,
        shortId: shortId(s.id),
        sourceName: nameByPlugin.get(s.source_plugin_id) ?? s.source_plugin_id,
        origin: s.source_plugin_id,
        hardware: s.device_label ?? "—",
        lastSync: agoLabel(s.last_seen_at),
        freshness: f.value,
        stale: f.stale,
      };
    });
}

// Honest coverage: one bar per SOURCE (the R2 model is one source → many device
// streams), each bar the mean freshness of that source's streams, and the
// headline the mean of those bars — a descriptive statistic over your own data,
// verifiable by eye. It is NOT a synthesized consensus of conflicting values;
// the product never claims one disagreeing source is "right".
export function buildCoverage(rows: ProvenanceRow[]): Coverage {
  const bySource = new Map<string, { label: string; values: number[]; anyFresh: boolean }>();
  for (const row of rows) {
    const group = bySource.get(row.origin) ?? { label: row.sourceName, values: [], anyFresh: false };
    group.values.push(row.freshness);
    if (!row.stale) group.anyFresh = true;
    bySource.set(row.origin, group);
  }
  const domains: CoverageDomain[] = [...bySource.entries()]
    .map(([id, g]) => ({
      id,
      label: g.label,
      pct: Math.round((g.values.reduce((a, b) => a + b, 0) / g.values.length) * 100),
      tone: g.anyFresh ? ("ok" as const) : ("warn" as const),
    }))
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 6);
  const headline = domains.length
    ? Math.round(domains.reduce((sum, d) => sum + d.pct, 0) / domains.length)
    : 0;
  return { headline, total: rows.length, domains };
}

// ── Demo fixtures ──────────────────────────────────────────────────────────
// A believable provenance story so a fresh clone (or the README screenshot)
// shows the Sources surface alive before any source is connected. Mirrors the
// approved design. Clearly labelled as demo wherever it renders.

export const DEMO_PROVENANCE: ProvenanceRow[] = [
  { streamId: "demo-hk-7f9a2b", shortId: "hk_7f9a2b", sourceName: "Apple Health", origin: "HealthSave iOS", hardware: "Apple Watch S8", lastSync: "2m ago", freshness: 1, stale: false },
  { streamId: "demo-wp-4c1e8d", shortId: "wp_4c1e8d", sourceName: "Whoop", origin: "Direct OAuth", hardware: "Whoop 4.0", lastSync: "12m ago", freshness: 0.92, stale: false },
  { streamId: "demo-hk-stat99x", shortId: "hk_stat_", sourceName: "HealthKit Statistics", origin: "Background Sync", hardware: "iPhone 14 Pro", lastSync: "45m ago", freshness: 0.72, stale: false },
  { streamId: "demo-ou-8v3n1p", shortId: "ou_8v3n1p", sourceName: "Oura Cloud", origin: "Webhook", hardware: "Gen 3 Ring", lastSync: "3h ago", freshness: 0.34, stale: true },
];

export const DEMO_DIVERGENCES: Divergence[] = [
  {
    metric: "Sleep Duration",
    context: "Last Night",
    readings: [
      { source: "Apple Watch", value: "6h 42m" },
      { source: "Whoop", value: "7h 18m" },
    ],
    resolution: "Both Kept",
    stance:
      "Wrist staging is probabilistic vs lab PSG, so a 36-min gap is expected. We keep both and never average them — narration leans on the more consistent nightly source, not a blended figure.",
  },
  {
    metric: "Recovery Trend Alignment",
    context: "",
    readings: [],
    resolution: "",
    warn: true,
    stance:
      "Whoop and Oura report RMSSD; Apple reports SDNN — different HRV definitions that are not comparable, so we never blend vendors. The 15%+ cross-source gap is the signal worth surfacing, not a number to resolve.",
    note: "Sources disagree on current trajectory. HRV delta between Whoop and Oura exceeds the 15% variance threshold over a 3-day rolling window.",
  },
];

// Derived from the demo rows by the SAME function the live path uses, so the
// headline is genuinely the mean of the per-source bars shown and the card
// summarizes the exact streams in the table beside it — demo and live tell one
// honest story (here Oura is stale, which is why coverage is not 100%).
export const DEMO_COVERAGE: Coverage = buildCoverage(DEMO_PROVENANCE);
