// One source of truth for rendering observation values, units, axis ticks,
// and relative time. Every card / table / chart routes through here so the
// same reading prints the same way everywhere.
//
// Two value formatters, by intent:
//   - formatValue: a reading shown to a human (cards, tables, hero numbers).
//                  Rounds large values, preserves one decimal for fractional
//                  readings, normalizes the unit and its spacing.
//   - formatTick:  a chart axis tick. Keeps two decimals for small fractional
//                  values so a 0.25 gridline doesn't collapse to "0".

export type FormatValueOptions = {
  // String used when the value is null/NaN. Defaults to an em dash.
  nullLabel?: string;
  // Force a specific number of decimals instead of the magnitude heuristic.
  decimals?: number;
};

export function normalizeUnit(unit: string | null | undefined): string | null {
  if (!unit) return null;
  if (unit === "degC") return "°C";
  return unit;
}

// Join a formatted number to its unit with the conventional spacing: no space
// before "%" or a degree sign ("5%", "0.3°C"), one space otherwise ("60 bpm").
export function joinUnit(body: string, unit: string | null | undefined): string {
  const u = normalizeUnit(unit);
  if (!u) return body;
  const space = u === "%" || u.startsWith("°") ? "" : " ";
  return `${body}${space}${u}`;
}

// Display formatter for a single reading.
export function formatValue(
  value: number | null | undefined,
  unit?: string | null,
  opts: FormatValueOptions = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return opts.nullLabel ?? "—";
  const abs = Math.abs(value);
  let body: string;
  if (typeof opts.decimals === "number") {
    body = value.toFixed(opts.decimals);
  } else if (abs >= 1000) {
    body = Math.round(value).toLocaleString();
  } else if (Number.isInteger(value)) {
    body = String(value);
  } else {
    // Small fractional readings (HRV 45.3, SpO₂ 97.5, temp 0.3) keep one
    // decimal; larger ones round so the number stays scannable.
    body = (abs < 100 ? value.toFixed(1) : String(Math.round(value)));
  }
  return joinUnit(body, unit);
}

// Axis-tick formatter.
export function formatTick(value: number): string {
  const a = Math.abs(value);
  if (a >= 1000) return Math.round(value).toLocaleString();
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(a < 1 ? 2 : 1);
}

// Relative time ("just now", "12m ago", "3h ago", "2d ago"). Relative to the
// current clock, so it is timezone-agnostic and safe in SSR.
export function formatAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
