// The ⌘K palette: the signal catalog streams in after the shell. The bug
// (audit web #23): the layout rendered a pages-only palette as the Suspense
// fallback and swapped in a new palette when the catalog arrived, so a palette
// opened early closed under the person and lost what they typed.
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Suspense, type ReactElement } from "react";

import { CommandPalette } from "./CommandPalette";
import { PaletteHost, ShellPalette } from "./PaletteHost";

describe("command palette", () => {
  test("the shell renders one palette instance; only its catalog waits", () => {
    const palette = ShellPalette() as ReactElement<{ catalog: ReactElement<{ fallback: unknown; children: ReactElement }> }>;
    expect(palette.type).toBe(CommandPalette);
    const catalog = palette.props.catalog;
    expect(catalog.type).toBe(Suspense);
    expect(catalog.props.fallback).toBeNull();
    expect(catalog.props.children.type).toBe(PaletteHost);
  });

  test("the layout never swaps a fallback palette for another", () => {
    const layout = readFileSync(join(import.meta.dir, "..", "layout.tsx"), "utf8");
    expect(layout).not.toMatch(/fallback=\{<CommandPalette/);
    expect(layout).toContain("<ShellPalette />");
  });
});
