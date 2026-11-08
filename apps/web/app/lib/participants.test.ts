import { describe, expect, test } from "bun:test";

import {
  DEFAULT_OWNER_ID,
  ownerCacheKey,
  ownerScope,
  parseOwnerCookie,
  readOwner,
  resolveViewedPerson,
  scopePath,
  switcherModel,
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

// One decision per request: who the reads are for, made from the cookie AND
// the server's own owner list. Every read, the switcher and the write guard
// use it, so the name on screen and the data under it cannot disagree.
describe("resolveViewedPerson", () => {
  const PRIMARY = { id: DEFAULT_OWNER_ID, label: null, is_default: true, active: true };
  const ALICE_ROW = { id: ALICE, label: "Alice", is_default: false, active: true };

  test("no participant cookie reads the primary person", () => {
    const person = resolveViewedPerson(null, null);
    expect(person).toEqual({ kind: "primary" });
    expect(readOwner(person)).toBeNull();
  });

  test("a listed participant is read as that person", () => {
    const person = resolveViewedPerson(ALICE, [PRIMARY, ALICE_ROW]);
    expect(person).toEqual({ kind: "participant", owner: ALICE });
    expect(readOwner(person)).toBe(ALICE);
  });

  test("a cookie naming someone the server does not list reads the primary person", () => {
    // The bug: the switcher showed "Primary person" while every read still
    // carried ?owner=<the unlisted id>.
    const person = resolveViewedPerson(ALICE, [PRIMARY]);
    expect(person).toEqual({ kind: "unlisted", requested: ALICE });
    expect(readOwner(person)).toBeNull();
  });

  test("an owner list that could not be read keeps the chosen person, unverified", () => {
    const person = resolveViewedPerson(ALICE, null);
    expect(person).toEqual({ kind: "unverified", owner: ALICE });
    expect(readOwner(person)).toBe(ALICE);
  });
});

describe("switcherModel", () => {
  const PRIMARY = { id: DEFAULT_OWNER_ID, label: null, is_default: true, active: true };
  const ALICE_ROW = { id: ALICE, label: "Alice", is_default: false, active: true };

  test("a single-person install with no cookie shows no select", () => {
    const model = switcherModel({ kind: "primary" }, [PRIMARY]);
    expect(model.options).toEqual([]);
    expect(model.notice).toBeNull();
    expect(model.clearCookie).toBe(false);
  });

  test("whenever the cookie scopes reads, the select is shown and names that person", () => {
    // The bug: with one listed owner, or a failed owner read, the switcher hid
    // while the cookie still scoped every read.
    for (const owners of [null, [PRIMARY], []]) {
      const model = switcherModel({ kind: "unverified", owner: ALICE }, owners);
      expect(model.current).toBe(ALICE);
      expect(model.options.map((option) => option.id)).toContain(ALICE);
      expect(model.options.map((option) => option.id)).toContain(DEFAULT_OWNER_ID);
      expect(model.notice).toBe("unverified");
    }
    const listed = switcherModel({ kind: "participant", owner: ALICE }, [ALICE_ROW]);
    expect(listed.current).toBe(ALICE);
    expect(listed.options.map((option) => option.id)).toEqual([DEFAULT_OWNER_ID, ALICE]);
  });

  test("an unlisted cookie falls back visibly to the primary person and is cleared", () => {
    const model = switcherModel({ kind: "unlisted", requested: ALICE }, [PRIMARY]);
    expect(model.current).toBe(DEFAULT_OWNER_ID);
    expect(model.notice).toBe("unlisted");
    expect(model.clearCookie).toBe(true);
  });

  test("the selected id is always one of the options when a select is shown", () => {
    const people = [
      { kind: "primary" } as const,
      { kind: "participant", owner: ALICE } as const,
      { kind: "unlisted", requested: ALICE } as const,
      { kind: "unverified", owner: ALICE } as const,
    ];
    for (const person of people) {
      for (const owners of [null, [], [PRIMARY], [PRIMARY, ALICE_ROW]]) {
        const model = switcherModel(person, owners);
        if (model.options.length > 0) {
          expect(model.options.map((option) => option.id)).toContain(model.current);
        }
        if (readOwner(person) !== null) expect(model.options.length).toBeGreaterThan(1);
      }
    }
  });
});
