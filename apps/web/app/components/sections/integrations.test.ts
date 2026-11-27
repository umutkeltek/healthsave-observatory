import { describe, expect, test } from "bun:test";

import type { SourceView } from "../../lib/api";
import { sourceCard } from "./IntegrationsSections";

const source = (lastSeen: string): SourceView => ({
  id: "s1",
  plugin_id: "apple-healthkit-ios",
  display_name: null,
  first_seen_at: "2026-01-01T00:00:00Z",
  last_seen_at: lastSeen,
});

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

describe("integration source cards", () => {
  // The bug: every source the server had ever seen was "connected", even one
  // last seen months ago.
  test("a source not seen for longer than the stale threshold is not called connected", () => {
    const card = sourceCard(source(hoursAgo(24 * 10)), undefined);
    expect(card.state).toBe("stale");
  });

  test("a source seen recently is connected", () => {
    expect(sourceCard(source(hoursAgo(1)), undefined).state).toBe("connected");
  });
});
