// Year in Health share card: a server-rendered SVG (1080 x 1350, the 4:5 size
// phone feeds show whole). One typeface (the system stack the web app uses),
// the dark tokens from DESIGN.md, one accent.
//
// Privacy rule, enforced by yearCard.test.ts: by default the card shows the
// shape of the year only. The year itself is the one number on it. Counts,
// dates, medians and device names appear only when the person opts in on the
// page (numbers=1, devices=1). Nothing on the card is computed here; it draws
// what the API returned.

import type { YearInHealth } from "./api";
import { daysInYear, MONTH_INITIALS, MONTH_NAMES, windowIndex } from "./year";

export const CARD_WIDTH = 1080;
export const CARD_HEIGHT = 1350;

export type CardOptions = {
  numbers: boolean;
  devices: boolean;
  // Set only by the preview script for seeded data; never read from a URL.
  synthetic?: boolean;
};

export const DEFAULT_CARD_OPTIONS: CardOptions = { numbers: false, devices: false };

/** Opt-ins from the page's query string. Anything but "1" means off. */
export function parseCardOptions(params: URLSearchParams): CardOptions {
  return { numbers: params.get("numbers") === "1", devices: params.get("devices") === "1" };
}

export function cardQuery(options: CardOptions): string {
  const qs = new URLSearchParams();
  if (options.numbers) qs.set("numbers", "1");
  if (options.devices) qs.set("devices", "1");
  const text = qs.toString();
  return text ? `?${text}` : "";
}

// DESIGN.md dark tokens (canvas, secondary, elevated, tertiary, text, muted,
// system blue, attention orange). No other colours on the card.
const C = {
  canvas: "#000000",
  secondary: "#1C1C1E",
  elevated: "#2C2C2E",
  tertiary: "#3A3A3C",
  ghost: "#636366",
  ink: "#F5F5F7",
  muted: "#98989D",
  accent: "#0A84FF",
  warn: "#FF9F0A",
};
const FONT = `-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'Segoe UI', system-ui, sans-serif`;

// Dial geometry.
const CX = 540;
const CY = 628;
const R_IN = 250; // where every day starts
const RAY = 168; // longest ray
const R_MONTH = 470; // month initials
const R_CHANGE = R_IN + RAY + 24; // device change marks

const LEVEL_OPACITY = [0, 0.38, 0.58, 0.8, 1];

function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function num(value: number): string {
  return Number(value.toFixed(2)).toString();
}

function polar(r: number, angle: number): [number, number] {
  return [CX + r * Math.cos(angle), CY + r * Math.sin(angle)];
}

// Day i of the calendar year sits at this angle; Jan 1 at twelve o'clock,
// running clockwise.
function angleOf(i: number, total: number): number {
  return -Math.PI / 2 + (2 * Math.PI * (i + 0.5)) / total;
}

function dayOfYear(year: number, iso: string): number {
  return Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.UTC(year, 0, 1)) / 86_400_000);
}

function text(
  x: number,
  y: number,
  content: string,
  attrs: { size: number; weight?: number; fill?: string; anchor?: "start" | "middle" | "end"; tracking?: number; className?: string },
): string {
  const parts = [
    `x="${num(x)}"`,
    `y="${num(y)}"`,
    `font-size="${attrs.size}"`,
    `font-weight="${attrs.weight ?? 400}"`,
    `fill="${attrs.fill ?? C.ink}"`,
    `text-anchor="${attrs.anchor ?? "start"}"`,
  ];
  if (attrs.tracking) parts.push(`letter-spacing="${num(attrs.tracking)}"`);
  if (attrs.className) parts.push(`class="${attrs.className}"`);
  return `<text ${parts.join(" ")}>${esc(content)}</text>`;
}

function dial(summary: YearInHealth): string[] {
  const total = daysInYear(summary.year);
  const maxCount = Math.max(1, ...summary.day_family_counts);
  const out: string[] = [];

  // Faint track under the whole year, so the circle reads complete even
  // where the year has not happened yet.
  out.push(`<circle cx="${CX}" cy="${CY}" r="${R_IN - 22}" fill="none" stroke="${C.secondary}" stroke-width="2"/>`);

  // Month boundaries and initials.
  for (let m = 0; m < 12; m++) {
    const start = dayOfYear(summary.year, `${summary.year}-${String(m + 1).padStart(2, "0")}-01`);
    const a0 = angleOf(start - 0.5, total);
    const [x1, y1] = polar(R_IN - 34, a0);
    const [x2, y2] = polar(R_IN - 12, a0);
    out.push(`<line x1="${num(x1)}" y1="${num(y1)}" x2="${num(x2)}" y2="${num(y2)}" stroke="${C.tertiary}" stroke-width="2" stroke-linecap="round"/>`);
    const nextStart = m === 11 ? total : dayOfYear(summary.year, `${summary.year}-${String(m + 2).padStart(2, "0")}-01`);
    const mid = angleOf((start + nextStart - 1) / 2, total);
    const [tx, ty] = polar(R_MONTH, mid);
    out.push(
      text(tx, ty + 9, MONTH_INITIALS[m], { size: 26, weight: 600, fill: C.muted, anchor: "middle", className: "month" }),
    );
  }

  // One mark per day of the calendar year.
  for (let d = 0; d < total; d++) {
    const iso = new Date(Date.UTC(summary.year, 0, 1 + d)).toISOString().slice(0, 10);
    const i = windowIndex(summary, iso);
    const angle = angleOf(d, total);
    if (i < 0) {
      // Not yet (the current year): a hairline dot on the track.
      const [x, y] = polar(R_IN + 4, angle);
      out.push(`<circle class="future" cx="${num(x)}" cy="${num(y)}" r="1.4" fill="${C.elevated}"/>`);
      continue;
    }
    const count = summary.day_family_counts[i] ?? 0;
    if (summary.mask[i] !== "1" || count === 0) {
      // A day with nothing recorded: always drawn, never skipped.
      const [x, y] = polar(R_IN + 4, angle);
      out.push(`<circle class="gap" cx="${num(x)}" cy="${num(y)}" r="2.2" fill="${C.ghost}"/>`);
      continue;
    }
    const share = Math.min(1, count / maxCount);
    const level = share > 0.75 ? 4 : share > 0.5 ? 3 : share > 0.25 ? 2 : 1;
    const length = 26 + (RAY - 26) * share;
    const [x1, y1] = polar(R_IN, angle);
    const [x2, y2] = polar(R_IN + length, angle);
    out.push(
      `<line class="day" x1="${num(x1)}" y1="${num(y1)}" x2="${num(x2)}" y2="${num(y2)}" stroke="${C.accent}" stroke-opacity="${LEVEL_OPACITY[level]}" stroke-width="2.6" stroke-linecap="round"/>`,
    );
  }

  // Device changes: a filled dot where a source first appears, a ring where
  // one stopped. Names only with the person's opt-in (listed below the dial).
  for (const change of summary.device_changes) {
    const d = dayOfYear(summary.year, change.day);
    if (d < 0 || d >= total) continue;
    const [x, y] = polar(R_CHANGE, angleOf(d, total));
    out.push(
      change.kind === "first_seen"
        ? `<circle class="change" cx="${num(x)}" cy="${num(y)}" r="8" fill="${C.warn}"/>`
        : `<circle class="change" cx="${num(x)}" cy="${num(y)}" r="7" fill="none" stroke="${C.warn}" stroke-width="3"/>`,
    );
  }

  // The year in the middle: the only number the card always carries.
  out.push(
    text(CX, CY + 40, String(summary.year), { size: 150, weight: 700, anchor: "middle", tracking: -5, className: "year" }),
  );
  out.push(
    text(CX, CY + 100, "YEAR IN HEALTH", { size: 24, weight: 600, fill: C.muted, anchor: "middle", tracking: 4.5 }),
  );
  return out;
}

function stat(x: number, value: string, label: string): string[] {
  return [
    text(x, 1176, value, { size: 64, weight: 700, anchor: "middle", tracking: -1.5, className: "stat" }),
    text(x, 1214, label, { size: 24, weight: 500, fill: C.muted, anchor: "middle" }),
  ];
}

function legend(y: number, withChanges: boolean): string[] {
  const out: string[] = [];
  const items: Array<{ mark: string; label: string; width: number }> = [
    {
      mark: `<line x1="0" y1="7" x2="0" y2="-11" stroke="${C.accent}" stroke-width="3" stroke-linecap="round"/>`,
      label: "data that day",
      width: 176,
    },
    { mark: `<circle cx="0" cy="-2" r="3.2" fill="${C.ghost}"/>`, label: "nothing recorded", width: 214 },
  ];
  if (withChanges) {
    items.push({ mark: `<circle cx="0" cy="-2" r="7" fill="${C.warn}"/>`, label: "new device", width: 156 });
  }
  const gap = 36;
  const total = items.reduce((sum, item) => sum + item.width, 0) + gap * (items.length - 1);
  let x = CX - total / 2;
  for (const item of items) {
    out.push(`<g transform="translate(${num(x + 6)} ${y})">${item.mark}</g>`);
    out.push(text(x + 24, y + 6, item.label, { size: 22, weight: 500, fill: C.muted }));
    x += item.width + gap;
  }
  return out;
}

function deviceLine(summary: YearInHealth): string | null {
  const parts = summary.device_changes.map((change) => {
    const month = MONTH_NAMES[Number(change.day.slice(5, 7)) - 1];
    return change.kind === "first_seen" ? `${change.label} from ${month}` : `${change.label} until ${month}`;
  });
  if (parts.length === 0) return null;
  const line = parts.join("  ·  ");
  return line.length > 72 ? `${line.slice(0, 71)}…` : line;
}

/** The card as an SVG document. */
export function renderYearCard(summary: YearInHealth, options: CardOptions = DEFAULT_CARD_OPTIONS): string {
  const body: string[] = [];
  body.push(`<rect width="${CARD_WIDTH}" height="${CARD_HEIGHT}" fill="${C.canvas}"/>`);
  body.push(text(72, 104, "HealthSave Observatory", { size: 26, weight: 600, fill: C.muted, tracking: 0.4 }));
  if (options.synthetic) {
    body.push(
      `<rect x="${CARD_WIDTH - 72 - 404}" y="70" width="404" height="50" rx="25" fill="none" stroke="${C.warn}" stroke-width="2"/>`,
    );
    body.push(
      text(CARD_WIDTH - 72 - 202, 104, "SYNTHETIC DATA · NOT A PERSON", {
        size: 20,
        weight: 700,
        fill: C.warn,
        anchor: "middle",
        tracking: 1.6,
        className: "synthetic",
      }),
    );
  }

  body.push(...dial(summary));

  const hasChanges = summary.device_changes.length > 0;
  if (options.numbers) {
    const days = summary.headlines.find((h) => h.id === "days_recorded");
    const sources = summary.headlines.find((h) => h.id === "sources");
    body.push(...stat(220, String(days?.value ?? summary.days_with_data), "days with data"));
    body.push(...stat(540, String(sources?.value ?? summary.sources.length), sources?.value === 1 ? "source" : "sources"));
    body.push(...stat(860, String(summary.longest_inside_gap), "longest gap, days"));
  }
  const devices = options.devices ? deviceLine(summary) : null;
  if (devices) {
    body.push(text(CX, options.numbers ? 1262 : 1196, devices, { size: 24, weight: 500, fill: C.ink, anchor: "middle", className: "devices" }));
  }
  body.push(...legend(options.numbers ? 1302 : 1262, hasChanges));

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${CARD_WIDTH}" height="${CARD_HEIGHT}" viewBox="0 0 ${CARD_WIDTH} ${CARD_HEIGHT}" font-family="${FONT}" role="img" aria-label="${esc(cardLabel(summary, options))}">`,
    `<title>${esc(cardLabel(summary, options))}</title>`,
    ...body,
    `</svg>`,
  ].join("\n");
}

/** Accessible description; follows the same opt-ins as the picture. */
export function cardLabel(summary: YearInHealth, options: CardOptions): string {
  const base = `${summary.year} in health: one mark per day, longer where more kinds of data were recorded, a dot where nothing was`;
  if (!options.numbers) return `${base}.`;
  return `${base}. ${summary.days_with_data} days with data, longest gap ${summary.longest_inside_gap} days.`;
}

/** Every piece of text the card will print (the test reads this too). */
export function cardTexts(svg: string): string[] {
  return [...svg.matchAll(/<(text|title)[^>]*>([^<]*)<\/\1>/g)].map((m) => m[2]);
}
