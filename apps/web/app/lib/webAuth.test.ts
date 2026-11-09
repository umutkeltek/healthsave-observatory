import { afterEach, describe, expect, test } from "bun:test";
import { NextRequest } from "next/server";

import { config as proxyConfig, proxy } from "../../proxy";
import {
  BARE_LAYOUT_HEADER,
  clientAddress,
  configuredWebPassword,
  createSessionToken,
  FailedLoginLimiter,
  isPublicRequest,
  isSameOriginPost,
  isValidSessionToken,
  passwordMatches,
  requestIsHttps,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  safeNextPath,
  sessionCredential,
} from "./webAuth";

const NOW = 1_800_000_000_000;

describe("session tokens", () => {
  test("a fresh token verifies with the same credential", async () => {
    const token = await createSessionToken("cred-one", NOW);
    expect(await isValidSessionToken(token, "cred-one", NOW + 1000)).toBe(true);
  });

  test("changing the password or the session secret signs every browser out", async () => {
    const before = sessionCredential({ WEB_PASSWORD: "pw", WEB_SESSION_SECRET: "s1" });
    const token = await createSessionToken(before, NOW);
    const newPassword = sessionCredential({ WEB_PASSWORD: "pw2", WEB_SESSION_SECRET: "s1" });
    const newSecret = sessionCredential({ WEB_PASSWORD: "pw", WEB_SESSION_SECRET: "s2" });
    expect(await isValidSessionToken(token, before, NOW + 1000)).toBe(true);
    expect(await isValidSessionToken(token, newPassword, NOW + 1000)).toBe(false);
    expect(await isValidSessionToken(token, newSecret, NOW + 1000)).toBe(false);
  });

  test("a token stops working when it expires", async () => {
    const token = await createSessionToken("cred", NOW);
    expect(await isValidSessionToken(token, "cred", NOW + SESSION_MAX_AGE_SECONDS * 1000 + 1)).toBe(false);
  });

  test("an edited expiry invalidates the signature", async () => {
    const token = await createSessionToken("cred", NOW);
    const [, sig] = token.split(".");
    const forged = `${NOW + 10 * SESSION_MAX_AGE_SECONDS * 1000}.${sig}`;
    expect(await isValidSessionToken(forged, "cred", NOW)).toBe(false);
  });

  test("malformed tokens and an empty credential are rejected", async () => {
    for (const token of [undefined, "", "abc", ".sig", "123", "12x.sig"]) {
      expect(await isValidSessionToken(token, "cred", NOW)).toBe(false);
    }
    expect(await isValidSessionToken(await createSessionToken("", NOW), "", NOW)).toBe(false);
  });

  test("no password means no credential, whatever the secret", () => {
    expect(sessionCredential({ WEB_SESSION_SECRET: "s" })).toBe("");
    expect(sessionCredential({ WEB_PASSWORD: " pw " })).toBe("\0pw");
  });
});

describe("password check", () => {
  test("matches only the exact password", async () => {
    expect(await passwordMatches("s3cret", "s3cret")).toBe(true);
    expect(await passwordMatches("s3cret ", "s3cret")).toBe(false);
    expect(await passwordMatches("", "s3cret")).toBe(false);
    expect(await passwordMatches("anything", "")).toBe(false);
  });

  test("WEB_PASSWORD is trimmed and empty means login is off", () => {
    expect(configuredWebPassword({ WEB_PASSWORD: "  abc \n" })).toBe("abc");
    expect(configuredWebPassword({})).toBe("");
  });
});

describe("redirect target after sign-in", () => {
  test("keeps same-origin paths with their query", () => {
    expect(safeNextPath("/sleep?range=30d")).toBe("/sleep?range=30d");
    expect(safeNextPath("/library/vital.hrv_sdnn")).toBe("/library/vital.hrv_sdnn");
  });

  test("refuses other origins, loops and characters a browser strips", () => {
    for (const raw of [
      null,
      "",
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "/\t/evil.example/phish",
      "/\n/evil.example",
      "/\r//evil.example",
      "/%09/evil.example".replace("%09", "\t"),
      "sleep",
      "/login",
      "/login?next=/x",
      "/auth/login",
    ]) {
      expect(safeNextPath(raw)).toBe("/");
    }
  });

  test("dot segments resolve inside this site", () => {
    expect(safeNextPath("/a/../sleep")).toBe("/sleep");
    expect(safeNextPath("/a/..//evil.example")).toBe("/");
  });
});

test("the Secure flag follows the scheme the browser used", () => {
  expect(requestIsHttps(new URL("http://box:4173/"), "https")).toBe(true);
  expect(requestIsHttps(new URL("http://box:4173/"), "http, https")).toBe(false);
  expect(requestIsHttps(new URL("https://box/"), null)).toBe(true);
  expect(requestIsHttps(new URL("http://box:4173/"), null)).toBe(false);
});

describe("cross-site form posts", () => {
  const headers = (init: Record<string, string>) => new Headers(init);

  test("Sec-Fetch-Site decides when the browser sends it", () => {
    expect(isSameOriginPost(headers({ "sec-fetch-site": "same-origin" }))).toBe(true);
    expect(isSameOriginPost(headers({ "sec-fetch-site": "same-site" }))).toBe(false);
    expect(isSameOriginPost(headers({ "sec-fetch-site": "cross-site" }))).toBe(false);
  });

  test("otherwise Origin must name this host, including the port", () => {
    expect(isSameOriginPost(headers({ origin: "http://box:4173", host: "box:4173" }))).toBe(true);
    expect(isSameOriginPost(headers({ origin: "http://box:3000", host: "box:4173" }))).toBe(false);
    expect(isSameOriginPost(headers({ origin: "null", host: "box:4173" }))).toBe(false);
  });

  test("a request with neither header is not from a browser page", () => {
    expect(isSameOriginPost(headers({}))).toBe(true);
  });
});

describe("failed sign-in limiter", () => {
  const A = "192.168.1.20";
  const B = "192.168.1.31";

  test("blocks after the limit and recovers when the window passes", () => {
    const limiter = new FailedLoginLimiter({ limit: 3, windowMs: 1000, globalLimit: 10 });
    for (let i = 0; i < 3; i++) limiter.recordFailure(A, NOW + i);
    expect(limiter.blocked(A, NOW + 10)).not.toBeNull();
    expect(limiter.blocked(A, NOW + 1003)).toBeNull();
  });

  // The bug: one process-wide bucket, so ten wrong guesses from anywhere that
  // reaches the port locked the owner out of their own dashboard.
  test("one address's wrong passwords do not lock out another address", () => {
    const limiter = new FailedLoginLimiter({ limit: 3, windowMs: 60_000, globalLimit: 10 });
    for (let i = 0; i < 3; i++) limiter.recordFailure(A, NOW + i);
    expect(limiter.blocked(A, NOW + 10)?.scope).toBe("client");
    expect(limiter.blocked(B, NOW + 10)).toBeNull();
  });

  test("a flood from many addresses still stops at the process-wide ceiling", () => {
    const limiter = new FailedLoginLimiter({ limit: 3, windowMs: 60_000, globalLimit: 5 });
    for (let i = 0; i < 5; i++) limiter.recordFailure(`10.0.0.${i}`, NOW + i);
    expect(limiter.blocked("10.0.0.99", NOW + 10)?.scope).toBe("everyone");
    expect(limiter.blocked(null, NOW + 10)?.scope).toBe("everyone");
  });

  test("requests with no known address share one bucket, as before", () => {
    const limiter = new FailedLoginLimiter({ limit: 3, windowMs: 60_000, globalLimit: 10 });
    for (let i = 0; i < 3; i++) limiter.recordFailure(null, NOW + i);
    expect(limiter.blocked(null, NOW + 10)?.scope).toBe("client");
    expect(limiter.blocked(A, NOW + 10)).toBeNull();
  });

  test("the wait is how long until the oldest counted failure leaves the window", () => {
    const limiter = new FailedLoginLimiter({ limit: 3, windowMs: 60_000, globalLimit: 10 });
    for (const offset of [0, 10_000, 20_000]) limiter.recordFailure(A, NOW + offset);
    expect(limiter.blocked(A, NOW + 30_000)?.retryAfterSeconds).toBe(30);
    expect(limiter.blocked(A, NOW + 59_500)?.retryAfterSeconds).toBe(1);
    expect(limiter.blocked(A, NOW + 60_000)).toBeNull();
  });

  test("a forgiven attempt no longer counts", () => {
    const limiter = new FailedLoginLimiter({ limit: 2, windowMs: 60_000, globalLimit: 2 });
    limiter.recordFailure(A, NOW);
    const ok = limiter.recordFailure(A, NOW + 1);
    expect(limiter.blocked(A, NOW + 2)?.scope).toBe("client");
    limiter.forgive(A, ok);
    expect(limiter.blocked(A, NOW + 2)).toBeNull();
  });

  test("the number of addresses it remembers is bounded", () => {
    const limiter = new FailedLoginLimiter({ limit: 3, windowMs: 60_000, globalLimit: 1_000_000, maxClients: 4 });
    for (let i = 0; i < 10; i++) limiter.recordFailure(`10.0.1.${i}`, NOW + i);
    expect(limiter.trackedClients()).toBeLessThanOrEqual(4);
  });
});

describe("client address for the limiter", () => {
  const h = (init: Record<string, string>) => new Headers(init);

  test("the hop nearest this app: the last X-Forwarded-For entry", () => {
    // A reverse proxy appends the address it saw; anything to its left came
    // from the client and can be made up.
    expect(clientAddress(h({ "x-forwarded-for": "6.6.6.6, 192.168.1.20" }))).toBe("192.168.1.20");
    expect(clientAddress(h({ "x-forwarded-for": " 192.168.1.20 " }))).toBe("192.168.1.20");
  });

  test("X-Real-IP when there is no X-Forwarded-For", () => {
    expect(clientAddress(h({ "x-real-ip": "192.168.1.31" }))).toBe("192.168.1.31");
  });

  test("no address at all is null (the shared bucket)", () => {
    expect(clientAddress(h({}))).toBeNull();
    expect(clientAddress(h({ "x-forwarded-for": " , " }))).toBeNull();
  });
});

describe("public requests", () => {
  test("only GET and HEAD reach /login without a session, so its server actions do not", () => {
    expect(isPublicRequest("/login", "GET")).toBe(true);
    expect(isPublicRequest("/login", "POST")).toBe(false);
    expect(isPublicRequest("/auth/login", "POST")).toBe(true);
    expect(isPublicRequest("/auth/login", "GET")).toBe(false);
    expect(isPublicRequest("/icon.svg", "GET")).toBe(true);
    expect(isPublicRequest("/icon.svg/x", "GET")).toBe(false);
    expect(isPublicRequest("/favicon.ico", "GET")).toBe(false);
  });
});

describe("proxy", () => {
  const original = { password: process.env.WEB_PASSWORD, secret: process.env.WEB_SESSION_SECRET };
  afterEach(() => {
    for (const [key, value] of [
      ["WEB_PASSWORD", original.password],
      ["WEB_SESSION_SECRET", original.secret],
    ] as const) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  });

  function signIn(password = "pw", secret = "") {
    process.env.WEB_PASSWORD = password;
    process.env.WEB_SESSION_SECRET = secret;
    return createSessionToken(sessionCredential());
  }

  function request(path: string, init: { method?: string; cookie?: string; headers?: Record<string, string> } = {}) {
    const headers = new Headers(init.headers);
    if (init.cookie) headers.set("cookie", `${SESSION_COOKIE}=${init.cookie}`);
    return new NextRequest(new URL(path, "http://box:4173"), { method: init.method ?? "GET", headers });
  }

  const forwarded = (response: Response, name: string) => response.headers.get(`x-middleware-request-${name}`);

  test("the matcher skips only hashed build output", () => {
    const pattern = new RegExp(`^${proxyConfig.matcher[0].replace("/(", "/(?:")}$`);
    for (const path of ["/favicon.ico", "/favicon.ico.x", "/icon.svg/x", "/_next/staticfoo", "/_next/image", "/sleep"]) {
      expect(pattern.test(path)).toBe(true);
    }
    expect(pattern.test("/_next/static/chunks/app.js")).toBe(false);
  });

  test("without WEB_PASSWORD every request passes", async () => {
    delete process.env.WEB_PASSWORD;
    const response = await proxy(request("/sleep"));
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  test("a page without a session redirects to /login and keeps the target", async () => {
    await signIn();
    const response = await proxy(request("/sleep?range=7d"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/sleep?range=7d");
  });

  test("paths that only 404 are behind sign-in too", async () => {
    await signIn();
    expect((await proxy(request("/favicon.ico"))).status).toBe(307);
    expect((await proxy(request("/icon.svg/x"))).status).toBe(307);
  });

  test("data routes and server actions without a session get 401, not a page", async () => {
    await signIn();
    expect((await proxy(request("/api/export?metric=hr"))).status).toBe(401);
    expect((await proxy(request("/api/v2/meta"))).status).toBe(401);
    expect((await proxy(request("/settings", { method: "POST", headers: { "next-action": "abc" } }))).status).toBe(401);
    expect((await proxy(request("/login", { method: "POST", headers: { "next-action": "abc" } }))).status).toBe(401);
  });

  test("an expired session on a server action answers text/plain, which the page can tell apart from a bug", async () => {
    await signIn();
    const response = await proxy(request("/settings", { method: "POST", headers: { "next-action": "abc" } }));
    expect(response.status).toBe(401);
    // Next's action client rejects with a text/plain error body as the message;
    // anything else becomes "An unexpected response was received from the server."
    expect(response.headers.get("content-type")).toBe("text/plain");
    expect(await response.text()).toBe("sign_in_required");
  });

  test("a valid session cookie passes", async () => {
    const token = await signIn();
    const response = await proxy(request("/api/export", { cookie: token }));
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  test("a cookie signed with another password or secret is refused", async () => {
    const oldPassword = await signIn("old-pw", "s");
    const oldSecret = await signIn("pw", "old-secret");
    await signIn("pw", "s");
    expect((await proxy(request("/sleep", { cookie: oldPassword }))).status).toBe(307);
    expect((await proxy(request("/sleep", { cookie: oldSecret }))).status).toBe(307);
  });

  test("the sign-in page, its form target, the healthcheck and the icon stay public", async () => {
    await signIn();
    for (const [path, method] of [
      ["/login", "GET"],
      ["/auth/login", "POST"],
      ["/api/health", "GET"],
      ["/icon.svg", "GET"],
    ]) {
      const response = await proxy(request(path, { method }));
      expect(response.headers.get("x-middleware-next")).toBe("1");
    }
  });

  test("only GET /login gets the bare layout, and a client cannot ask for it", async () => {
    const token = await signIn();
    expect(forwarded(await proxy(request("/login")), BARE_LAYOUT_HEADER)).toBe("1");

    const spoofed = await proxy(request("/sleep", { cookie: token, headers: { [BARE_LAYOUT_HEADER]: "1" } }));
    expect(spoofed.headers.get("x-middleware-next")).toBe("1");
    expect(forwarded(spoofed, BARE_LAYOUT_HEADER)).toBeNull();
  });
});
