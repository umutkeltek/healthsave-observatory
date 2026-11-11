import { afterEach, beforeEach, expect, test } from "bun:test";
import { inRequest } from "../../lib/testRequest";
import { clearSwrCache } from "../../lib/ttlCache";
import { DEFAULT_OWNER_ID, PARTICIPANT_COOKIE } from "../../lib/participants";
import { GET, POST } from "./[[...path]]/route";

const realFetch = globalThis.fetch;
const ID = "11111111-1111-4111-8111-111111111111";
const ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
let calls: { url: string; init?: RequestInit }[] = [];
beforeEach(() => {
  clearSwrCache(); calls = [];
  globalThis.fetch = (async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/api/v2/owners")) return Response.json({ owners: [
      { id: DEFAULT_OWNER_ID, is_default: true }, { id: ALICE, is_default: false },
    ], count: 2 });
    calls.push({ url: String(url), init });
    return Response.json({ id: ID }, { status: 201 });
  }) as typeof fetch;
});
afterEach(() => { globalThis.fetch = realFetch; clearSwrCache(); });
const context = (path: string[] = []) => ({ params: Promise.resolve({ path }) });
const post = (origin: string, body: BodyInit = "synthetic") => new Request("http://box:4173/api/lab-imports", {
  method: "POST", headers: { origin, host: "box:4173", "x-file-name": "report.csv" }, body,
});

test("cross-origin and origin-less imports never reach the private backend", async () => {
  for (const origin of ["https://attacker.invalid", "null", ""]) {
    const response = await inRequest("", () => POST(post(origin), context()));
    expect(response.status).toBe(403);
  }
  expect(calls).toHaveLength(0);
});

test("primary-person upload forwards exact bytes and returns private cache policy", async () => {
  const response = await inRequest("", () => POST(post("http://box:4173"), context()));
  expect(response.status).toBe(201);
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  expect(calls).toHaveLength(1);
  expect(calls[0].url).toEndWith("/api/v2/lab-imports");
  expect(new TextDecoder().decode(calls[0].init?.body as Uint8Array)).toBe("synthetic");
});

test("a reverse-proxied browser origin is checked against public headers, not Next's internal URL", async () => {
  const request = new Request("http://0.0.0.0:4173/api/lab-imports", {
    method: "POST", headers: { origin: "https://labs.example", host: "0.0.0.0:4173",
      "x-forwarded-host": "labs.example", "sec-fetch-site": "same-origin", "x-file-name": "report.csv" }, body: "synthetic",
  });
  expect((await inRequest("", () => POST(request, context()))).status).toBe(201);
  const crossed = new Request("http://0.0.0.0:4173/api/lab-imports", {
    method: "POST", headers: { origin: "https://attacker.invalid", host: "labs.example",
      "sec-fetch-site": "cross-site" }, body: "synthetic",
  });
  expect((await inRequest("", () => POST(crossed, context()))).status).toBe(403);
});

test("selected participant cannot read originals or import into primary record", async () => {
  const cookie = `${PARTICIPANT_COOKIE}=${ALICE}`;
  expect((await inRequest(cookie, () => POST(post("http://box:4173"), context()))).status).toBe(403);
  expect((await inRequest(cookie, () => GET(new Request(`http://box:4173/api/lab-imports/${ID}/original`), context([ID, "original"])))).status).toBe(403);
  expect(calls).toHaveLength(0);
});

test("oversized request and unknown action are rejected without forwarding", async () => {
  const response = await inRequest("", () => POST(post("http://box:4173", new Uint8Array(5 * 1024 * 1024 + 1)), context()));
  expect(response.status).toBe(413);
  expect((await inRequest("", () => GET(new Request("http://box:4173/api/lab-imports/anything"), context(["anything"])))).status).toBe(404);
  expect(calls).toHaveLength(0);
});
