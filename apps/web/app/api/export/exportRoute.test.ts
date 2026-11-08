// The export proxy, run as Next runs it (a request scope with cookies) against
// a stubbed backend. No module mocks.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import { DEFAULT_OWNER_ID, PARTICIPANT_COOKIE } from "../../lib/participants";
import { inRequest } from "../../lib/testRequest";
import { clearSwrCache } from "../../lib/ttlCache";
import { GET } from "./route";

const ALICE = "7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00";
const PRIMARY = { id: DEFAULT_OWNER_ID, label: null, is_default: true, active: true, scopes: [], created_at: null, last_ingest_at: null };
const ALICE_ROW = { ...PRIMARY, id: ALICE, label: "Alice", is_default: false };

const realFetch = globalThis.fetch;
let owners: unknown[] = [];
let exported: string[] = [];

beforeEach(() => {
  clearSwrCache();
  exported = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v2/owners")) return Response.json({ count: owners.length, owners });
    if (url.includes("/api/v2/export")) {
      exported.push(url);
      return Response.json({ rows: [] });
    }
    return Response.json({ detail: "unexpected" }, { status: 500 });
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  clearSwrCache();
});

const download = (cookie: string) =>
  inRequest(cookie, () => GET(new Request("http://box:4173/api/export?metric=heart_rate&format=json")));

describe("/api/export follows the person on screen", () => {
  // The bug: the route read the raw cookie, so a cookie naming someone the
  // server no longer lists exported under that id while the page showed the
  // primary person.
  test("a cookie naming an unlisted owner exports the primary person", async () => {
    owners = [PRIMARY];
    const response = await download(`${PARTICIPANT_COOKIE}=${ALICE}`);
    expect(response.status).toBe(200);
    expect(exported).toHaveLength(1);
    expect(exported[0]).not.toContain("owner=");
  });

  test("a listed participant exports that participant", async () => {
    owners = [PRIMARY, ALICE_ROW];
    await download(`${PARTICIPANT_COOKIE}=${ALICE}`);
    expect(exported[0]).toContain(`owner=${ALICE}`);
  });

  test("no cookie exports the primary person", async () => {
    owners = [PRIMARY, ALICE_ROW];
    await download("");
    expect(exported[0]).not.toContain("owner=");
  });
});
