import { describe, expect, test } from "bun:test";
import { readFileSync, existsSync } from "fs";
import { resolve } from "path";

const CSS_PATH = resolve(__dirname, "globals.css");

if (!existsSync(CSS_PATH)) {
  throw new Error(`CSS file not found: ${CSS_PATH}`);
}

const css = readFileSync(CSS_PATH, "utf-8");

// ── DESIGN.md token rules ─────────────────────────────────────────

const ROOT_TOKENS = new Set([
  "--canvas",
  "--surface",
  "--tertiary",
  "--ink",
  "--muted",
  "--line",
  "--hover",
  "--pressed",
  "--sidebar",
  "--blue",
  "--up",
  "--warn",
  "--down",
  "--sleep",
  "--neutral",
  "--series-1",
  "--series-2",
  "--series-3",
  "--series-4",
  "--series-5",
  "--series-6",
  "--dial-color",
  "--on-accent",
]);

function hardcodedColors(cssText: string): string[] {
  // Hex colors outside of :root token definitions. Ignores legacy
  // transition shorthands ("transition: color 180ms") and SVG stroke/fill
  // attributes inside inline SVGs.
  const hex = /#[0-9a-fA-F]{3,8}/g;
  const lines = cssText.split("\n");
  const violations: string[] = [];
  let inRootBlock = false;
  let rootDepth = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let depth = rootDepth;

    if (line.includes(":root {") || line.includes(":root{")) {
      inRootBlock = true;
      rootDepth = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      continue;
    }

    if (inRootBlock) {
      depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      if (depth <= 0) {
        inRootBlock = false;
        rootDepth = 0;
      }
      continue;
    }

    // Skip comments and SVG attributes
    if (line.trim().startsWith("/*") || line.includes("stroke=") || line.includes("fill=")) continue;

    if (line.includes("[data-theme")) {
      const themeDepth = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      let j = i + 1;
      let td = themeDepth;
      while (j < lines.length && td > 0) {
        td += (lines[j].match(/\{/g) || []).length - (lines[j].match(/\}/g) || []).length;
        j++;
      }
      i = j; // skip dark mode block
      continue;
    }

    const matches = line.match(hex);
    if (matches) {
      for (const m of matches) {
        violations.push(`L${i + 1}: hardcoded hex ${m} — use a CSS custom property token`);
      }
    }
  }
  return violations;
}

type SelectorBlock = { selector: string; line: number; body: string };

function topLevelSelectors(cssText: string): SelectorBlock[] {
  // Extract every top-level selector block (not inside @media, [data-theme],
  // @keyframes, @import, @charset, @layer, @supports). Handles multi-line
  // selector lists (``html,\nbody {``) by stitching trailing-comma fragments.
  //
  // Depth is updated exactly once per line so a multi-line block can't desync
  // the scan (the previous version advanced `i` past a block during body
  // capture and then subtracted the closing brace again, driving depth
  // negative and silently dropping every selector after the first).
  const blocks: SelectorBlock[] = [];
  const lines = cssText.split("\n");
  const braces = (s: string) => (s.match(/\{/g) || []).length - (s.match(/\}/g) || []).length;

  const isIgnoredStart = (s: string): boolean =>
    s.startsWith("@media") || s.startsWith("[data-theme") ||
    s.startsWith("@keyframes") || s.startsWith("@font-") ||
    s.startsWith("@import") || s.startsWith("@charset") ||
    s.startsWith("@layer") || s.startsWith("@supports");

  let depth = 0;
  let pendingPrefix = "";
  let pendingLine = -1;

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    const atTop = depth === 0;

    if (atTop && trimmed && !trimmed.startsWith("/*") && !trimmed.startsWith("//") &&
        trimmed.includes("{") && !isIgnoredStart(trimmed)) {
      // Stitch a multi-line selector list together.
      let selectorLines = [trimmed];
      while (!selectorLines[selectorLines.length - 1].includes("{") && i + 1 < lines.length) {
        i += 1;
        selectorLines.push(lines[i].trim());
      }
      let selector = selectorLines.join(" ").split("{")[0].trim();
      const selectorStartLine = pendingPrefix ? pendingLine : i + 1;
      if (pendingPrefix) selector = `${pendingPrefix} ${selector}`.replace(/\s*,\s*/g, ", ");
      // Capture body lines until the brace depth opened on the selector line closes.
      const body: string[] = [];
      let d = braces(lines[i]); // the selector line itself opens the block
      let j = i;
      while (j + 1 < lines.length && d > 0) {
        j += 1;
        const ln = lines[j];
        if (!ln.trim().startsWith("/*")) body.push(ln);
        d += braces(ln);
      }
      // d is now 0; consume through the closing brace line.
      i = j;
      if (selector) {
        blocks.push({ selector, line: selectorStartLine, body: body.join("\n") });
      }
      pendingPrefix = "";
      pendingLine = -1;
      // The block (open…close) nets to zero braces, so depth is unchanged.
      continue;
    }

    if (atTop && trimmed.endsWith(",")) {
      pendingPrefix = pendingPrefix ? `${pendingPrefix} ${trimmed}` : trimmed;
      if (pendingLine === -1) pendingLine = i + 1;
    } else if (atTop) {
      pendingPrefix = "";
      pendingLine = -1;
    }

    depth += braces(lines[i]);
  }

  return blocks;
}

function duplicateBlocks(blocks: SelectorBlock[]): Map<string, { lines: number[]; bodies: string[] }> {
  const bySelector = new Map<string, SelectorBlock[]>();
  for (const block of blocks) {
    const arr = bySelector.get(block.selector) || [];
    arr.push(block);
    bySelector.set(block.selector, arr);
  }
  const dups = new Map<string, { lines: number[]; bodies: string[] }>();
  for (const [sel, list] of bySelector) {
    if (list.length > 1) {
      dups.set(sel, {
        lines: list.map((b) => b.line),
        bodies: list.map((b) => b.body),
      });
    }
  }
  return dups;
}

function conflictingDuplicates(
  dups: Map<string, { lines: number[]; bodies: string[] }>,
): Array<{ selector: string; property: string; values: { line: number; value: string }[] }> {
  // For each duplicated selector, parse out the property: value declarations
  // from each body and report any property whose value differs across copies.
  const violations: Array<{ selector: string; property: string; values: { line: number; value: string }[] }> = [];
  for (const [selector, { lines, bodies }] of dups) {
    const perCopy = bodies.map((body) => {
      const props = new Map<string, string>();
      for (const raw of body.split("\n")) {
        const line = raw.replace(/\/\*.*?\*\//g, "").trim();
        if (!line || line.startsWith("/*")) continue;
        const m = line.match(/^([a-zA-Z-][a-zA-Z0-9-]*)\s*:\s*(.+?);?\s*$/);
        if (m) props.set(m[1], m[2].replace(/;$/, "").trim());
      }
      return props;
    });
    const allProps = new Set<string>();
    perCopy.forEach((p) => p.forEach((_, k) => allProps.add(k)));
    for (const prop of allProps) {
      const seen = perCopy
        .map((p, i) => (p.has(prop) ? { line: lines[i], value: p.get(prop)! } : null))
        .filter((x): x is { line: number; value: string } => x !== null);
      const distinct = new Set(seen.map((s) => s.value));
      if (distinct.size > 1) {
        violations.push({ selector, property: prop, values: seen });
      }
    }
  }
  return violations;
}

function usesSystemFonts(cssText: string): string[] {
  const violations: string[] = [];
  const forbiddenFonts = ["Roboto", "Open Sans", "Material", "Lato", "Montserrat", "Poppins", "Inter", "Georgia"];
  const lines = cssText.split("\n");
  for (let i = 0; i < lines.length; i++) {
    for (const font of forbiddenFonts) {
      if (lines[i].includes(font)) {
        violations.push(`L${i + 1}: forbidden font "${font}" — use the Apple system font stack`);
      }
    }
  }
  return violations;
}

describe("CSS design-token enforcement (DESIGN.md)", () => {
  test("no hardcoded hex colours outside :root token definitions", () => {
    const violations = hardcodedColors(css);
    // Global CSS will always have a few intentional hex references (box-shadow,
    // SVG inline attrs); assert they do not exist in unexpected patterns.
    // The real gate: any hex in component/pages that isn't a token reference
    // is a violation. Right now we accept zero hex outside :root.
    if (violations.length > 0) {
      // Filter: some may be rgba hex values used as fallbacks
      const nonRgba = violations.filter((v) => !v.includes("rgba"));
      expect(nonRgba).toEqual([]);
    }
    expect(violations.length).toBe(0);
  });

  test("no duplicate top-level selectors with conflicting property values", () => {
    // DESIGN.md: "A duplicate top-level selector is a bug, not a layer." The
    // dangerous case is one selector defined twice with DISAGREEING values for
    // a property — the earlier silently loses to source order.
    //
    // History: this gate existed before but was a no-op because the
    // topLevelSelectors parser desynced on multi-line blocks and dropped every
    // selector after the first. The parser is now correct, which surfaced a
    // backlog of override-layer conflicts that accumulated while it was broken.
    //
    // Rather than blind-merge 68 conflicting declarations across a 7k-line
    // stylesheet (repositioning properties in the cascade can change how a
    // selector resolves against its neighbours — needs visual verification),
    // we RATCHET: the gate fails if the conflict count GROWS, and the baseline
    // is lowered as each override block is consolidated. The full list is
    // printed every run so the debt stays visible and actionable.
    const blocks = topLevelSelectors(css);
    const dups = duplicateBlocks(blocks);
    const conflicts = conflictingDuplicates(dups);

    // Lower these baselines as override layers are consolidated away.
    // Conflicts are at 0 now (Tier A removed the 68 losing declarations);
    // any NEW conflict is a hard failure. Duplicates remain until the
    // visually-verified Tier B collapse.
    const CONFLICT_BASELINE = 0;
    const DUPLICATE_BASELINE = 41;

    if (conflicts.length > 0) {
      const summary = conflicts
        .map((c) => {
          const vals = c.values.map((v) => `L${v.line}=${v.value}`).join(" vs ");
          return `${c.selector} { ${c.property}: ${vals} }`;
        })
        .join("\n  ");
      console.warn(
        `[cssRules] ${conflicts.length} conflicting duplicate declarations (baseline ${CONFLICT_BASELINE}, lower as you consolidate):\n  ${summary}`,
      );
    }
    if (dups.size > 0) {
      console.warn(
        `[cssRules] ${dups.size} top-level selectors defined >1× (baseline ${DUPLICATE_BASELINE}): ${[...dups.keys()].join(", ")}`,
      );
    }

    // Ratchet: never let the debt grow. Lower the baselines when you fix some.
    expect(conflicts.length).toBeLessThanOrEqual(CONFLICT_BASELINE);
    expect(dups.size).toBeLessThanOrEqual(DUPLICATE_BASELINE);
  });

  test("no banned font families — Apple system stack only", () => {
    const violations = usesSystemFonts(css);
    expect(violations).toEqual([]);
  });

  test("baseline ribbons never use dash-length draw animation", () => {
    const ribbonBlocks = Array.from(
      css.matchAll(/([^{}]*\.ribbon-trace[^{}]*)\{([^{}]*)\}/g),
      (match) => ({ selector: match[1], body: match[2] }),
    );
    const animatedSelectors = ribbonBlocks
      .filter((block) =>
        block.body.includes("stroke-dasharray") || block.body.includes("animation: draw"),
      )
      .map((block) => block.selector.trim());

    expect(animatedSelectors).toEqual([]);
  });
});
