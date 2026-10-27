import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { NextRequest } from "next/server";

import { proxy } from "../../proxy";
import { createSessionToken, SESSION_COOKIE } from "./webAuth";
import {
  checkNewWebPassword,
  resetWebAuthStoreForTests,
  resolveWebAuth,
  storeWebPassword,
  storeWebSignInOff,
  verifyWebPassword,
} from "./webAuthStore.server";

const saved = {
  file: process.env.WEB_AUTH_FILE,
  password: process.env.WEB_PASSWORD,
  secret: process.env.WEB_SESSION_SECRET,
};
let dir = "";

beforeEach(async () => {
  dir = mkdtempSync(join(tmpdir(), "hs-web-auth-"));
  process.env.WEB_AUTH_FILE = join(dir, "data", "web-auth.json");
  delete process.env.WEB_PASSWORD;
  delete process.env.WEB_SESSION_SECRET;
  await resetWebAuthStoreForTests();
});

afterEach(async () => {
  await resetWebAuthStoreForTests();
  rmSync(dir, { recursive: true, force: true });
  for (const [key, value] of [
    ["WEB_AUTH_FILE", saved.file],
    ["WEB_PASSWORD", saved.password],
    ["WEB_SESSION_SECRET", saved.secret],
  ] as const) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

describe("where the sign-in setting comes from", () => {
  test("nothing set means sign-in is off", async () => {
    expect(await resolveWebAuth()).toEqual({ source: "none", mode: "off", credential: "" });
  });

  test("WEB_PASSWORD from .env applies when Settings has never been used", async () => {
    process.env.WEB_PASSWORD = "env-password";
    const auth = await resolveWebAuth();
    expect(auth.source).toBe("env");
    expect(auth.mode).toBe("password");
    expect(await verifyWebPassword("env-password")).toBe(true);
  });

  test("a password saved in Settings replaces the .env one", async () => {
    process.env.WEB_PASSWORD = "env-password";
    await storeWebPassword("settings-password");
    const auth = await resolveWebAuth();
    expect(auth.source).toBe("settings");
    expect(await verifyWebPassword("settings-password")).toBe(true);
    expect(await verifyWebPassword("env-password")).toBe(false);
  });

  test("turning sign-in off in Settings wins over .env too", async () => {
    process.env.WEB_PASSWORD = "env-password";
    await storeWebSignInOff();
    expect(await resolveWebAuth()).toEqual({ source: "settings", mode: "off", credential: "" });
    expect(await verifyWebPassword("env-password")).toBe(false);
  });

  test("deleting the file (healthsave web-password reset) hands control back to .env", async () => {
    process.env.WEB_PASSWORD = "env-password";
    await storeWebSignInOff();
    rmSync(process.env.WEB_AUTH_FILE!);
    expect((await resolveWebAuth()).source).toBe("env");
  });

  test("a damaged file is unreadable, never off", async () => {
    await storeWebPassword("settings-password");
    writeFileSync(process.env.WEB_AUTH_FILE!, "{not json");
    expect((await resolveWebAuth()).mode).toBe("unreadable");
    expect(await verifyWebPassword("settings-password")).toBe(false);
  });
});

describe("the stored file", () => {
  test("holds a salted scrypt hash, never the password, and is owner-only", async () => {
    await storeWebPassword("settings-password");
    const raw = readFileSync(process.env.WEB_AUTH_FILE!, "utf8");
    expect(raw).not.toContain("settings-password");
    const stored = JSON.parse(raw);
    expect(stored.mode).toBe("password");
    expect(Buffer.from(stored.hash, "base64")).toHaveLength(32);
    expect(statSync(process.env.WEB_AUTH_FILE!).mode & 0o777).toBe(0o600);
  });

  test("changing the password changes the session key, so old cookies stop working", async () => {
    await storeWebPassword("first-password");
    const first = (await resolveWebAuth()).credential;
    await storeWebPassword("first-password");
    const second = (await resolveWebAuth()).credential;
    expect(first).not.toBe(second);
  });
});

test("new passwords need a minimum length, no edge spaces and a matching repeat", () => {
  expect(checkNewWebPassword("short", "short")).toContain("at least");
  expect(checkNewWebPassword(" leading-space-pass", " leading-space-pass")).toContain("spaces");
  expect(checkNewWebPassword("long-enough-pass", "different-pass")).toContain("do not match");
  expect(checkNewWebPassword("long-enough-pass", "long-enough-pass")).toBeNull();
});

describe("proxy with a Settings password", () => {
  const request = (path: string, cookie?: string) =>
    new NextRequest(new URL(path, "http://box:4173"), {
      headers: cookie ? { cookie: `${SESSION_COOKIE}=${cookie}` } : {},
    });

  test("asks for sign-in, and accepts a cookie signed with the stored credential", async () => {
    await storeWebPassword("settings-password");
    expect((await proxy(request("/sleep"))).status).toBe(307);
    const token = await createSessionToken((await resolveWebAuth()).credential);
    expect((await proxy(request("/sleep", token))).headers.get("x-middleware-next")).toBe("1");
  });

  test("lets everything through once sign-in is turned off", async () => {
    process.env.WEB_PASSWORD = "env-password";
    await storeWebSignInOff();
    expect((await proxy(request("/sleep"))).headers.get("x-middleware-next")).toBe("1");
  });

  test("refuses everything but the healthcheck while the file is damaged", async () => {
    await storeWebPassword("settings-password");
    writeFileSync(process.env.WEB_AUTH_FILE!, "{not json");
    expect((await proxy(request("/sleep"))).status).toBe(503);
    expect((await proxy(request("/login"))).status).toBe(503);
    expect((await proxy(request("/api/health"))).headers.get("x-middleware-next")).toBe("1");
  });
});
