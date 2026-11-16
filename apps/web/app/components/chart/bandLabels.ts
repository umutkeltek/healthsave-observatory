// Where the two usual-range labels sit on a per-day chart, so that neither
// ever sits on the line. Each label tries the band's left end, its right end,
// the inside of the band, then points along it; the first spot the trace
// does not cross wins. With no clear spot the label is left out: the answer
// line and the values table still state the range.
//
// The plot's width is not known on the server, so a label's width is taken
// as a share of the narrowest plot drawn (MIN_PLOT_W). On any wider plot the
// real label covers less, inside the box that was checked, so the answer
// holds at every width. Heights are real pixels.

// px; these match .ribbon-edge-label in globals.css
export const BAND_LABEL = {
  gap: 5, // from the band edge
  height: 11, // 10.5px type, line-height 1
  char: 6.4, // advance of one mono character at 10.5px
  inset: 4, // from the plot's end
  halo: 3, // the text-stroke halo
  clear: 2, // half the trace stroke, plus a pixel of air
};
export const MIN_PLOT_W = 240;

export type BandLabelSpot = { at: "left" | "right" | number; side: "above" | "below" };
type Box = { x0: number; x1: number; y0: number; y1: number };
type Point = readonly [number, number]; // x as a fraction of the width, y in px

const ALONG = [0.25, 0.5, 0.75];

function labelBox(spot: BandLabelSpot, edge: number, text: string): Box {
  const { gap, height, char, inset, halo } = BAND_LABEL;
  const reach = (inset + text.length * char + halo) / MIN_PLOT_W;
  const [x0, x1] =
    spot.at === "left"
      ? [0, reach]
      : spot.at === "right"
        ? [1 - reach, 1]
        : [spot.at - halo / MIN_PLOT_W, spot.at + (text.length * char + halo) / MIN_PLOT_W];
  const [y0, y1] =
    spot.side === "above" ? [edge - gap - height, edge - gap] : [edge + gap, edge + gap + height];
  return { x0, x1, y0, y1 };
}

// Every drawn piece of the trace: a segment between two neighbouring days,
// or a lone point between two gaps.
function pieces(trace: (Point | null)[]): [Point, Point][] {
  const out: [Point, Point][] = [];
  trace.forEach((p, i) => {
    if (!p) return;
    const next = trace[i + 1];
    if (next) out.push([p, next]);
    else if (!trace[i - 1]) out.push([p, p]);
  });
  return out;
}

export function crossesBox(trace: (Point | null)[], box: Box): boolean {
  const lo = box.y0 - BAND_LABEL.clear;
  const hi = box.y1 + BAND_LABEL.clear;
  return pieces(trace).some(([a, b]) => {
    if (Math.max(a[0], b[0]) < box.x0 || Math.min(a[0], b[0]) > box.x1) return false;
    const span = b[0] - a[0];
    const yAt = (x: number) =>
      span === 0 ? a[1] : a[1] + (b[1] - a[1]) * Math.min(1, Math.max(0, (x - a[0]) / span));
    const ys = span === 0 ? [a[1], b[1]] : [yAt(box.x0), yAt(box.x1)];
    return Math.max(...ys) >= lo && Math.min(...ys) <= hi;
  });
}

const overlaps = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

export function placeBandLabels({
  trace,
  top,
  bottom,
  height,
  high,
  low,
}: {
  trace: (Point | null)[]; // one entry per day; null for a day with no reading
  top: number; // the band's upper edge, px from the plot's top
  bottom: number; // its lower edge
  height: number; // the plot's height, px
  high: string; // label for the upper edge
  low: string;
}): { high: BandLabelSpot | null; low: BandLabelSpot | null } {
  const roomTop = -10; // labels may reach into the space above the plot
  const pick = (
    text: string,
    edge: number,
    outside: "above" | "below",
    fits: (box: Box, side: "above" | "below") => boolean,
    first: BandLabelSpot["at"] = "left",
  ): { spot: BandLabelSpot; box: Box } | null => {
    const inside: BandLabelSpot["side"] = outside === "above" ? "below" : "above";
    const ends: BandLabelSpot["at"][] = first === "right" ? ["right", "left"] : ["left", "right"];
    const order: BandLabelSpot[] = [
      ...ends.map((at) => ({ at, side: outside })),
      ...ends.map((at) => ({ at, side: inside })),
      ...ALONG.flatMap((at) => [
        { at, side: outside },
        { at, side: inside },
      ]),
    ];
    for (const spot of order) {
      const box = labelBox(spot, edge, text);
      if (box.y0 < roomTop || box.y1 > height) continue;
      if (!fits(box, spot.side)) continue;
      if (crossesBox(trace, box)) continue;
      return { spot, box };
    }
    return null;
  };
  const { gap } = BAND_LABEL;
  const upper = pick(high, top, "above", (box, side) => side === "above" || box.y1 <= bottom - gap);
  const lower = pick(
    low,
    bottom,
    "below",
    (box, side) =>
      (side === "below" || box.y0 >= top + gap) && !(upper && overlaps(box, upper.box)),
    typeof upper?.spot.at === "string" ? upper.spot.at : "left",
  );
  return { high: upper?.spot ?? null, low: lower?.spot ?? null };
}
