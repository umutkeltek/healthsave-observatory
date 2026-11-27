// A privacy read that failed must not report the narrator as off.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { Privacy } from "../../lib/api";
import { narratorState } from "../../lib/narrator";
import { clearSwrCache } from "../../lib/ttlCache";
import { IntegrationsSection } from "./IntegrationsSections";
import { briefSummaryLabel } from "./TodaySections";

const realFetch = globalThis.fetch;
const realWarn = console.warn;

beforeEach(() => {
  clearSwrCache();
  console.warn = () => {};
  globalThis.fetch = (async () => Response.json({ detail: "boom" }, { status: 500 })) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  console.warn = realWarn;
  clearSwrCache();
});

describe("narrator state when the privacy read fails", () => {
  test("is unknown, not off", () => {
    expect(narratorState(null)).toBe("unknown");
    expect(narratorState({ provider: "" } as Privacy)).toBe("off");
    expect(narratorState({ provider: "ollama" } as Privacy)).toBe("on");
  });

  // The bug: `!privacy || isNarratorOff(...)` said "Off" for a failed read.
  test("Integrations does not say the narrator is off", async () => {
    const html = renderToStaticMarkup(await IntegrationsSection());
    expect(html).not.toContain("Off. Findings remain computed evidence only.");
    expect(html).toContain("Narrator state unknown");
  });

  test("Today's brief summary does not say briefs are off", () => {
    expect(briefSummaryLabel("unknown")).toBe("Status unknown");
    expect(briefSummaryLabel("off")).toBe("Briefs are off");
    expect(briefSummaryLabel("on")).toBe("Not available yet");
  });
});
