import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";

import LoginPage from "../../login/page";
import { FAILED_LOGIN_LIMIT } from "../../lib/webAuth";
import { passwordAttempts, resetWebAuthStoreForTests } from "../../lib/webAuthStore.server";
import { POST } from "./route";

const saved = { password: process.env.WEB_PASSWORD, file: process.env.WEB_AUTH_FILE };
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
  await resetWebAuthStoreForTests();
  rmSync(dir, { recursive: true, force: true });
  for (const [key, value] of [
    ["WEB_PASSWORD", saved.password],
    ["WEB_AUTH_FILE", saved.file],
  ] as const) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

function signIn(password: string): Promise<Response> {
  const body = new FormData();
  body.set("password", password);
  body.set("next", "/sleep");
  return POST(
    new Request("http://box:4173/auth/login", { method: "POST", body, headers: { "sec-fetch-site": "same-origin" } }),
  );
}

describe("sign-in limiter", () => {
  // The bug: once blocked, the browser form landed on a raw JSON body,
  // {"detail":"too_many_attempts"}, with no way back.
  test("a blocked sign-in returns to the sign-in page with a readable reason", async () => {
    for (let i = 0; i < FAILED_LOGIN_LIMIT; i++) passwordAttempts.recordFailure();
    const response = await signIn("correct horse battery");
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/login?error=locked&next=%2Fsleep");
    expect(response.headers.get("retry-after")).toBe("60");
  });

  test("the sign-in page says to wait, distinct from a wrong password", async () => {
    const locked = renderToStaticMarkup(await LoginPage({ searchParams: Promise.resolve({ error: "locked" }) }));
    expect(locked).toContain("Too many wrong passwords. Wait a minute and try again.");
    expect(locked).not.toContain("That password is not right.");
    const wrong = renderToStaticMarkup(await LoginPage({ searchParams: Promise.resolve({ error: "1" }) }));
    expect(wrong).toContain("That password is not right.");
  });
});
