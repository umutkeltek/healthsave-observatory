// The ⌘K palette: the signal catalog streams in after the shell. The bug
// (audit web #23): the layout rendered a pages-only palette as the Suspense
// fallback. React does not hydrate a pending fallback, so the palette could
// not open until the catalog arrived, and then a new instance replaced it.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { isValidElement, Suspense, type ReactElement, type ReactNode } from "react";

import RootLayout from "../layout";
import { inRequest } from "../lib/testRequest";
import { resetWebAuthStoreForTests } from "../lib/webAuthStore.server";
import { CommandPalette } from "./CommandPalette";
import { PaletteHost, ShellPalette } from "./PaletteHost";

const saved = { password: process.env.WEB_PASSWORD, file: process.env.WEB_AUTH_FILE };
let dir = "";

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "hs-palette-"));
  process.env.WEB_AUTH_FILE = join(dir, "web-auth.json");
  delete process.env.WEB_PASSWORD;
});

afterEach(async () => {
  await resetWebAuthStoreForTests();
  rmSync(dir, { recursive: true, force: true });
  for (const [key, value] of [
    ["WEB_PASSWORD", saved.password],
    ["WEB_AUTH_FILE", saved.file],
  ] as const) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

type Found = { inSuspense: boolean };

// Every CommandPalette in an element tree, and whether it sits inside a
// Suspense boundary (as its child or its fallback). ShellPalette is expanded,
// since it is what the layout renders.
function palettes(node: ReactNode, inSuspense = false, found: Found[] = []): Found[] {
  if (Array.isArray(node)) {
    for (const child of node) palettes(child, inSuspense, found);
    return found;
  }
  if (!isValidElement(node)) return found;
  const element = node as ReactElement<Record<string, unknown>>;
  if (element.type === ShellPalette) return palettes(ShellPalette(), inSuspense, found);
  if (element.type === CommandPalette) found.push({ inSuspense });
  const nested = inSuspense || element.type === Suspense;
  for (const value of Object.values(element.props)) {
    if (isValidElement(value) || Array.isArray(value)) palettes(value as ReactNode, nested, found);
  }
  return found;
}

describe("command palette", () => {
  test("the layout renders one palette, outside any boundary that waits for data", async () => {
    const tree = await inRequest("", () => RootLayout({ children: null }));
    const found = palettes(tree);
    expect(found).toEqual([{ inSuspense: false }]);
  });

  test("only the catalog waits", () => {
    const palette = ShellPalette() as ReactElement<{ catalog: ReactElement<{ fallback: unknown; children: ReactElement }> }>;
    expect(palette.type).toBe(CommandPalette);
    expect(palette.props.catalog.type).toBe(Suspense);
    expect(palette.props.catalog.props.fallback).toBeNull();
    expect(palette.props.catalog.props.children.type).toBe(PaletteHost);
  });
});
