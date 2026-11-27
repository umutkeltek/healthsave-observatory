import { afterEach, beforeEach, expect, test } from "bun:test";
import { inRequest } from "../../lib/testRequest";
import { clearSwrCache } from "../../lib/ttlCache";
import { DEFAULT_OWNER_ID, PARTICIPANT_COOKIE } from "../../lib/participants";
import { DELETE, GET, POST } from "./[[...path]]/route";

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
test("upload retries preserve request identity and history cursors survive the proxy", async () => {
  const request = post("http://box:4173");
  request.headers.set("x-upload-id", ID);
  await inRequest("", () => POST(request, context()));
  expect(new Headers(calls[0].init?.headers).get("x-upload-id")).toBe(ID);
  const cursor = "synthetic+/cursor==";
  await inRequest("", () => GET(new Request(`http://box:4173/api/genetics?${new URLSearchParams({ cursor })}`), context()));
  expect(new URL(calls[1].url).searchParams.get("cursor")).toBe(cursor);
});
const context = (path: string[] = []) => ({ params: Promise.resolve({ path }) });
const post = (origin: string, body: BodyInit = "synthetic") => new Request("http://box:4173/api/genetics", {
  method: "POST", headers: { origin, host: "box:4173", "x-file-name": "synthetic.vcf" }, body,
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
  expect(calls[0].url).toEndWith("/api/v2/genetics");
  expect(new TextDecoder().decode(calls[0].init?.body as Uint8Array)).toBe("synthetic");
});

test("a reverse-proxied browser origin is checked against public headers, not Next's internal URL", async () => {
  const request = new Request("http://0.0.0.0:4173/api/genetics", {
    method: "POST", headers: { origin: "https://labs.example", host: "0.0.0.0:4173",
      "x-forwarded-host": "labs.example", "sec-fetch-site": "same-origin", "x-file-name": "synthetic.vcf" }, body: "synthetic",
  });
  expect((await inRequest("", () => POST(request, context()))).status).toBe(201);
  const crossed = new Request("http://0.0.0.0:4173/api/genetics", {
    method: "POST", headers: { origin: "https://attacker.invalid", host: "labs.example",
      "sec-fetch-site": "cross-site" }, body: "synthetic",
  });
  expect((await inRequest("", () => POST(crossed, context()))).status).toBe(403);
});

test("selected participant cannot read originals or import into primary record", async () => {
  const cookie = `${PARTICIPANT_COOKIE}=${ALICE}`;
  expect((await inRequest(cookie, () => POST(post("http://box:4173"), context()))).status).toBe(403);
  expect((await inRequest(cookie, () => GET(new Request(`http://box:4173/api/genetics/${ID}/original`), context([ID, "original"])))).status).toBe(403);
  expect(calls).toHaveLength(0);
});

test("oversized request and unknown action are rejected without forwarding", async () => {
  const response = await inRequest("", () => POST(post("http://box:4173", new Uint8Array(50 * 1024 * 1024 + 1)), context()));
  expect(response.status).toBe(413);
  expect((await inRequest("", () => GET(new Request("http://box:4173/api/genetics/anything"), context(["anything"])))).status).toBe(404);
  expect(calls).toHaveLength(0);
});

test("deletion enforces origin and person before forwarding the confirmation", async () => {
  const request = (origin: string) => new Request(`http://box:4173/api/genetics/${ID}`, {
    method: "DELETE", headers: { origin, host: "box:4173" }, body: JSON.stringify({ confirmation: ID }),
  });
  expect((await inRequest("", () => DELETE(request("https://attacker.invalid"), context([ID])))).status).toBe(403);
  expect((await inRequest(`${PARTICIPANT_COOKIE}=${ALICE}`, () => DELETE(request("http://box:4173"), context([ID])))).status).toBe(403);
  expect(calls).toHaveLength(0);
  expect((await inRequest("", () => DELETE(request("http://box:4173"), context([ID])))).status).toBe(201);
  expect(calls[0].init?.method).toBe("DELETE");
  expect(JSON.parse(new TextDecoder().decode(calls[0].init?.body as Uint8Array))).toEqual({ confirmation: ID });
});

test("consent and build headers are forwarded without unrelated client headers", async () => {
  const request = new Request("http://box:4173/api/genetics", { method: "POST", body: "synthetic", headers: {
    origin: "http://box:4173", host: "box:4173", "x-file-name": "synthetic.vcf",
    "x-genome-assembly": "GRCh38", "x-genetic-consent": "accepted", "x-forward-strand": "confirmed",
    "x-retain-original": "true", "x-personal-note": "must not be forwarded",
  }});
  await inRequest("", () => POST(request, context()));
  const headers = new Headers(calls[0].init?.headers);
  expect(headers.get("x-genome-assembly")).toBe("GRCh38");
  expect(headers.get("x-genetic-consent")).toBe("accepted");
  expect(headers.get("x-forward-strand")).toBe("confirmed");
  expect(headers.get("x-retain-original")).toBe("true");
  expect(headers.has("x-personal-note")).toBe(false);
});

test("control actions have a smaller body limit and original removal has an explicit route", async () => {
  const request = (body: string) => new Request(`http://box:4173/api/genetics/${ID}/original`, {
    method: "DELETE", headers: { origin: "http://box:4173", host: "box:4173" }, body,
  });
  expect((await inRequest("", () => DELETE(request("x".repeat(4097)), context([ID, "original"])))).status).toBe(413);
  expect(calls).toHaveLength(0);
  await inRequest("", () => DELETE(request(JSON.stringify({ confirmation: ID })), context([ID, "original"])));
  expect(calls[0].url).toEndWith(`/api/v2/genetics/${ID}/original`);
});
