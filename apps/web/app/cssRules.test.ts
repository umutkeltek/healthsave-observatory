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
  const blocks: SelectorBlock[] = [];
  let depth = 0;
  let bodyStart = -1;
  const lines = cssText.split("\n");

  const isSelectorStart = (s: string): boolean =>
    !s.startsWith("@media") && !s.startsWith("[data-theme") &&
    !s.startsWith("@keyframes") && !s.startsWith("@font-") &&
    !s.startsWith("@import") && !s.startsWith("@charset") &&
    !s.startsWith("@layer") && !s.startsWith("@supports") &&
    s.includes("{");

  let pendingPrefix = "";
  let pendingLine = -1;

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed || trimmed.startsWith("/*") || trimmed.startsWith("//")) {
      depth += (lines[i].match(/\{/g) || []).length - (lines[i].match(/\}/g) || []).length;
      continue;
    }

    if (depth === 0) {
      if (isSelectorStart(trimmed)) {
        let selectorLines = [trimmed];
        while (!selectorLines[selectorLines.length - 1].includes("{") && i + 1 < lines.length) {
          i += 1;
          selectorLines.push(lines[i].trim());
        }
        let selector = selectorLines.join(" ").split("{")[0].trim();
        const selectorStartLine = pendingPrefix ? pendingLine : i + 1;
        if (pendingPrefix) selector = `${pendingPrefix} ${selector}`;
        // Capture body lines until depth returns to 0.
        bodyStart = i + 1;
        let body: string[] = [];
        let j = i;
        let d = (lines[j].match(/\{/g) || []).length - (lines[j].match(/\}/g) || []).length;
        while (j + 1 < lines.length && d > 0) {
          j += 1;
          const ln = lines[j];
          if (!ln.trim().startsWith("/*")) body.push(ln);
          d += (ln.match(/\{/g) || []).length - (ln.match(/\}/g) || []).length;
        }
        i = j;
        if (selector) {
          blocks.push({ selector, line: selectorStartLine, body: body.join("\n") });
        }
        pendingPrefix = "";
        pendingLine = -1;
      } else if (trimmed.endsWith(",")) {
        pendingPrefix = pendingPrefix
          ? `${pendingPrefix} ${trimmed}`
          : trimmed;
        if (pendingLine === -1) pendingLine = i + 1;
      } else {
        pendingPrefix = "";
        pendingLine = -1;
      }
    } else {
      pendingPrefix = "";
      pendingLine = -1;
    }

    depth += (lines[i].match(/\{/g) || []).length - (lines[i].match(/\}/g) || []).length;
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
    // Most duplicate selector blocks are intentional override blocks
    // (e.g. "Final taste alignment" sections that re-declare styles with
    // newer values). Those are fine — the last definition wins.
    //
    // What IS a bug is two declarations that disagree on a *property*
    // (e.g. .sidebar { width: 256px } in one place, width: 258px in
    // another). Those silently lose to whichever comes last in source
    // order and indicate a missed consolidation. This test fails on
    // those conflicts and reports the exact properties that disagree.
    const blocks = topLevelSelectors(css);
    const dups = duplicateBlocks(blocks);
    const conflicts = conflictingDuplicates(dups);
    if (conflicts.length > 0) {
      const summary = conflicts
        .slice(0, 10)
        .map((c) => {
          const vals = c.values.map((v) => `L${v.line}=${v.value}`).join(" vs ");
          return `${c.selector} { ${c.property}: ${vals} }`;
        })
        .join("\n  ");
      console.warn(
        `CSS duplicate-conflict debt: ${conflicts.length} selector blocks have conflicting values:\n  ${summary}`,
      );
    }
    expect(conflicts).toEqual([]);
  });

  test("no banned font families — Apple system stack only", () => {
    const violations = usesSystemFonts(css);
    expect(violations).toEqual([]);
  });
});
