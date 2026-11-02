import { describe, expect, test } from "bun:test";

import {
  DEFAULT_OWNER_ID,
  ownerCacheKey,
  ownerScope,
  parseOwnerCookie,
  scopePath,
  withOwner,
} from "./participants";

const ALICE = "7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00";

describe("parseOwnerCookie", () => {
  test("a participant uuid is the selected owner", () => {
    expect(parseOwnerCookie(ALICE)).toBe(ALICE);
    expect(parseOwnerCookie(ALICE.toUpperCase())).toBe(ALICE);
  });

  test("missing, malformed and the primary person all mean the primary view", () => {
    for (const raw of [undefined, null, "", "alice", `${ALICE}x`, DEFAULT_OWNER_ID]) {
      expect(parseOwnerCookie(raw)).toBeNull();
    }
  });
});

describe("ownerScope", () => {
  test("owner-scoped reads mirror the server's ?owner= routes", () => {
    for (const path of [
      "/api/v2/metrics/vital.heart_rate/series?range=7d",
      "/api/v2/series?ids=a,b&range=30d",
      "/api/v2/export/metrics",
      "/api/v2/export?metric=all",
      "/api/v2/sources",
      "/api/v2/devices",
      "/api/v2/streams",
      `/api/v2/streams/${ALICE}`,
      "/api/v2/readiness",
    ]) {
      expect(ownerScope(path)).toBe("scoped");
    }
  });

  test("host-wide surfaces are neutral", () => {
    for (const path of [
      "/api/v2/metrics",
      "/api/v2/meta",
      "/api/v2/owners",
      "/api/v2/privacy",
      "/api/v2/intelligence",
      "/api/v2/intelligence/detect-local",
      "/api/v2/changes",
    ]) {
      expect(ownerScope(path)).toBe("neutral");
    }
  });

  test("analysis and records of the primary person stay primary-only", () => {
    for (const path of [
      "/api/v2/insights/latest",
      "/api/v2/insights/findings?type=anomaly",
      "/api/v2/experiments",
      "/api/v2/experiments/candidates",
      "/api/v2/moments?limit=50",
      "/api/v2/receipts?limit=20",
      "/api/v2/settings/analytical-time",
      "/api/v2/some-route-added-later",
    ]) {
      expect(ownerScope(path)).toBe("primary");
    }
  });
});

describe("scopePath", () => {
  test("the primary view reads every path unchanged", () => {
    expect(scopePath("/api/v2/insights/latest", null)).toBe("/api/v2/insights/latest");
    expect(scopePath("/api/v2/readiness", null)).toBe("/api/v2/readiness");
  });

  test("a participant view adds owner= to scoped reads and blocks primary-only ones", () => {
    expect(scopePath("/api/v2/readiness", ALICE)).toBe(`/api/v2/readiness?owner=${ALICE}`);
    expect(scopePath("/api/v2/series?ids=a&range=7d", ALICE)).toBe(
      `/api/v2/series?ids=a&range=7d&owner=${ALICE}`,
    );
    expect(scopePath("/api/v2/privacy", ALICE)).toBe("/api/v2/privacy");
    expect(scopePath("/api/v2/insights/findings", ALICE)).toBeNull();
  });

  test("withOwner encodes the value", () => {
    expect(withOwner("/x", "a b")).toBe("/x?owner=a%20b");
  });
});

describe("ownerCacheKey", () => {
  test("one person's cached answer never serves another", () => {
    expect(ownerCacheKey("readiness", null)).toBe("readiness");
    expect(ownerCacheKey("readiness", ALICE)).toBe(`readiness@owner:${ALICE}`);
    expect(ownerCacheKey("readiness", ALICE)).not.toBe(ownerCacheKey("readiness", null));
  });
});
