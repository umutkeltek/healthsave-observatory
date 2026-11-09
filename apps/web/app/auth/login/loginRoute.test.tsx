import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";

import LoginPage from "../../login/page";
import { getDictionary } from "../../lib/i18n";
import { inRequest } from "../../lib/testRequest";
import { FAILED_LOGIN_GLOBAL_LIMIT, FAILED_LOGIN_LIMIT } from "../../lib/webAuth";
import { passwordAttempts, resetWebAuthStoreForTests } from "../../lib/webAuthStore.server";
import { POST } from "./route";

const saved = {
  password: process.env.WEB_PASSWORD,
  file: process.env.WEB_AUTH_FILE,
  locales: process.env.HEALTHSAVE_EXPERIMENTAL_LOCALES,
};
let dir = "";

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "hs-login-"));
  process.env.WEB_AUTH_FILE = join(dir, "data", "web-auth.json");
  process.env.WEB_PASSWORD = "correct horse battery";
  // A fixed past clock: the limiter's failures from this file are long expired
  // once the real clock is back, so no other test sees them.
  setSystemTime(new Date("2020-01-01T00:00:00Z"));
});

afterEach(async () => {
  setSystemTime();
  passwordAttempts.reset();
  await resetWebAuthStoreForTests();
  rmSync(dir, { recursive: true, force: true });
  for (const [key, value] of [
    ["WEB_PASSWORD", saved.password],
    ["WEB_AUTH_FILE", saved.file],
    ["HEALTHSAVE_EXPERIMENTAL_LOCALES", saved.locales],
  ] as const) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

function signIn(password: string, from?: string): Promise<Response> {
  const body = new FormData();
  body.set("password", password);
  body.set("next", "/sleep");
  const headers: Record<string, string> = { "sec-fetch-site": "same-origin" };
  if (from) headers["x-forwarded-for"] = from;
  return POST(new Request("http://box:4173/auth/login", { method: "POST", body, headers }));
}

function renderLogin(params: { error?: string; wait?: string }, cookie = ""): Promise<string> {
  return inRequest(cookie, async () =>
    renderToStaticMarkup(await LoginPage({ searchParams: Promise.resolve(params) })),
  );
}

describe("sign-in limiter", () => {
  // The bug: once blocked, the browser form landed on a raw JSON body,
  // {"detail":"too_many_attempts"}, with no way back.
  test("a blocked sign-in returns to the sign-in page with how long to wait", async () => {
    for (let i = 0; i < FAILED_LOGIN_LIMIT; i++) passwordAttempts.recordFailure(null);
    const response = await signIn("correct horse battery");
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/login?error=locked&wait=60&next=%2Fsleep");
    expect(response.headers.get("retry-after")).toBe("60");
  });

  // The bug: one bucket for the whole process, so wrong guesses from any
  // address that reaches the port locked the owner out everywhere.
  test("wrong passwords from one address do not lock out the owner at another", async () => {
    for (let i = 0; i < FAILED_LOGIN_LIMIT; i++) passwordAttempts.recordFailure("192.168.1.66");
    const owner = await signIn("correct horse battery", "192.168.1.20");
    expect(owner.headers.get("location")).toBe("/sleep");
    expect(owner.headers.get("set-cookie")).toContain("hs_session=");
    const guesser = await signIn("correct horse battery", "192.168.1.66");
    expect(guesser.headers.get("location")).toStartWith("/login?error=locked&wait=");
  });

  test("a flood over many addresses pauses sign-in for everyone", async () => {
    for (let i = 0; i < FAILED_LOGIN_GLOBAL_LIMIT; i++) passwordAttempts.recordFailure(`10.9.${i}.1`);
    const response = await signIn("correct horse battery", "192.168.1.20");
    expect(response.headers.get("location")).toStartWith("/login?error=paused&wait=");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  test("a wrong password counts against the address it came from", async () => {
    const before = passwordAttempts.trackedClients();
    const response = await signIn("wrong", "192.168.1.66");
    expect(response.headers.get("location")).toBe("/login?error=1&next=%2Fsleep");
    expect(passwordAttempts.trackedClients()).toBe(before + 1);
    expect(passwordAttempts.blocked("192.168.1.20")).toBeNull();
  });

  // Before: a guess was counted only after the password check finished, so
  // guesses sent all at once were every one checked before the first counted.
  test("guesses sent at once cannot all slip past the limit", async () => {
    const answers = await Promise.all(
      Array.from({ length: FAILED_LOGIN_LIMIT + 5 }, () => signIn("wrong", "192.168.1.66")),
    );
    const checked = answers.filter((r) => r.headers.get("location")?.startsWith("/login?error=1"));
    expect(checked.length).toBe(FAILED_LOGIN_LIMIT);
  });

  test("a right password does not count against the address", async () => {
    for (let i = 0; i < FAILED_LOGIN_LIMIT + 2; i++) {
      const response = await signIn("correct horse battery", "192.168.1.20");
      expect(response.headers.get("location")).toBe("/sleep");
    }
    expect(passwordAttempts.blocked("192.168.1.20")).toBeNull();
  });

  test("the sign-in page says how long to wait, distinct from a wrong password", async () => {
    const locked = await renderLogin({ error: "locked", wait: "42" });
    expect(locked).toContain("Too many wrong passwords. Try again in 42 seconds.");
    expect(locked).not.toContain("That password is not right.");
    const paused = await renderLogin({ error: "paused", wait: "1" });
    expect(paused).toContain("sign-in is paused for everyone. Try again in 1 second.");
    const noWait = await renderLogin({ error: "locked", wait: "soon" });
    expect(noWait).toContain("Try again in a minute.");
    const wrong = await renderLogin({ error: "1" });
    expect(wrong).toContain("That password is not right.");
  });

  test("the sign-in page speaks the interface language, never half English", async () => {
    process.env.HEALTHSAVE_EXPERIMENTAL_LOCALES = "1";
    const html = await renderLogin({ error: "locked", wait: "42" }, "locale=ja");
    const ja = getDictionary("ja").signIn;
    expect(html).toContain("42 秒後にもう一度お試しください。");
    expect(html).toContain(ja.prompt);
    for (const english of Object.values(getDictionary("en").signIn)) {
      if (english.includes("{")) continue;
      expect(html).not.toContain(english);
    }
  });
});
