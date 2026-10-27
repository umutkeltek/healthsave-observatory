import { afterEach, describe, expect, test } from "bun:test";
import { NextRequest } from "next/server";

import { proxy } from "../../proxy";
import {
  BARE_LAYOUT_HEADER,
  configuredWebPassword,
  createSessionToken,
  isValidSessionToken,
  passwordMatches,
  requestIsHttps,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  safeNextPath,
} from "./webAuth";

const NOW = 1_800_000_000_000;

describe("session tokens", () => {
  test("a fresh token verifies with the same password", async () => {
    const token = await createSessionToken("pw-one", NOW);
    expect(await isValidSessionToken(token, "pw-one", NOW + 1000)).toBe(true);
  });

  test("changing the password signs every browser out", async () => {
    const token = await createSessionToken("pw-one", NOW);
    expect(await isValidSessionToken(token, "pw-two", NOW + 1000)).toBe(false);
  });

  test("a token stops working when it expires", async () => {
    const token = await createSessionToken("pw-one", NOW);
    expect(await isValidSessionToken(token, "pw-one", NOW + SESSION_MAX_AGE_SECONDS * 1000 + 1)).toBe(false);
  });

  test("an edited expiry invalidates the signature", async () => {
    const token = await createSessionToken("pw-one", NOW);
    const [, sig] = token.split(".");
    const forged = `${NOW + 10 * SESSION_MAX_AGE_SECONDS * 1000}.${sig}`;
    expect(await isValidSessionToken(forged, "pw-one", NOW)).toBe(false);
  });

  test("malformed tokens and an empty password are rejected", async () => {
    for (const token of [undefined, "", "abc", ".sig", "123", "12x.sig"]) {
      expect(await isValidSessionToken(token, "pw-one", NOW)).toBe(false);
    }
    expect(await isValidSessionToken(await createSessionToken("", NOW), "", NOW)).toBe(false);
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
  });

  test("refuses other origins and loops", () => {
    for (const raw of [null, "", "https://evil.example", "//evil.example", "/\\evil.example", "sleep", "/login", "/auth/login"]) {
      expect(safeNextPath(raw)).toBe("/");
    }
  });
});

test("the Secure flag follows the scheme the browser used", () => {
  expect(requestIsHttps(new URL("http://box:4173/"), "https")).toBe(true);
  expect(requestIsHttps(new URL("http://box:4173/"), "http, https")).toBe(false);
  expect(requestIsHttps(new URL("https://box/"), null)).toBe(true);
  expect(requestIsHttps(new URL("http://box:4173/"), null)).toBe(false);
});

describe("proxy", () => {
  const original = process.env.WEB_PASSWORD;
  afterEach(() => {
    if (original === undefined) delete process.env.WEB_PASSWORD;
    else process.env.WEB_PASSWORD = original;
  });

  function request(path: string, init: { method?: string; cookie?: string; headers?: Record<string, string> } = {}) {
    const headers = new Headers(init.headers);
    if (init.cookie) headers.set("cookie", `${SESSION_COOKIE}=${init.cookie}`);
    return new NextRequest(new URL(path, "http://box:4173"), { method: init.method ?? "GET", headers });
  }

  const forwarded = (response: Response, name: string) => response.headers.get(`x-middleware-request-${name}`);

  test("without WEB_PASSWORD every request passes", async () => {
    delete process.env.WEB_PASSWORD;
    const response = await proxy(request("/sleep"));
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  test("a page without a session redirects to /login and keeps the target", async () => {
    process.env.WEB_PASSWORD = "pw";
    const response = await proxy(request("/sleep?range=7d"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/sleep?range=7d");
  });

  test("data routes and server actions without a session get 401, not a page", async () => {
    process.env.WEB_PASSWORD = "pw";
    expect((await proxy(request("/api/export?metric=hr"))).status).toBe(401);
    expect((await proxy(request("/api/v2/meta"))).status).toBe(401);
    expect((await proxy(request("/settings", { method: "POST", headers: { "next-action": "abc" } }))).status).toBe(401);
  });

  test("a valid session cookie passes", async () => {
    process.env.WEB_PASSWORD = "pw";
    const response = await proxy(request("/api/export", { cookie: await createSessionToken("pw") }));
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  test("a cookie signed with another password is refused", async () => {
    process.env.WEB_PASSWORD = "pw";
    const response = await proxy(request("/sleep", { cookie: await createSessionToken("old-pw") }));
    expect(response.status).toBe(307);
  });

  test("the sign-in page, its form target and the healthcheck stay public", async () => {
    process.env.WEB_PASSWORD = "pw";
    for (const [path, method] of [["/login", "GET"], ["/auth/login", "POST"], ["/api/health", "GET"]]) {
      const response = await proxy(request(path, { method }));
      expect(response.headers.get("x-middleware-next")).toBe("1");
    }
  });

  test("only /login gets the bare layout, and a client cannot ask for it", async () => {
    process.env.WEB_PASSWORD = "pw";
    const login = await proxy(request("/login"));
    expect(forwarded(login, BARE_LAYOUT_HEADER)).toBe("1");

    const spoofed = await proxy(
      request("/sleep", { cookie: await createSessionToken("pw"), headers: { [BARE_LAYOUT_HEADER]: "1" } }),
    );
    expect(spoofed.headers.get("x-middleware-next")).toBe("1");
    expect(forwarded(spoofed, BARE_LAYOUT_HEADER)).toBeNull();
  });
});
