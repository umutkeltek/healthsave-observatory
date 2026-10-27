import { randomBytes, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { mkdir, readFile, rename, stat, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { promisify } from "node:util";

import { configuredWebPassword, FailedLoginLimiter, passwordMatches, sessionCredential } from "./webAuth";

// Where the web sign-in setting lives, in priority order:
//   1. data/web-auth.json, written from Settings (scrypt hash or "off")
//   2. WEB_PASSWORD in .env (setup generates it)
//   3. nothing: sign-in is off
// The file sits on the web container's own volume and never holds the password
// itself. `healthsave web-password reset` deletes it, which hands control back
// to .env (the way back in if the Settings password is forgotten).

const scrypt = promisify(scryptCallback) as (password: string, salt: Buffer, keylen: number) => Promise<Buffer>;
const KEY_LENGTH = 32;
export const MIN_WEB_PASSWORD_LENGTH = 10;

export type StoredWebAuth =
  | { version: 1; mode: "password"; salt: string; hash: string; sessionSecret: string; updatedAt: string }
  | { version: 1; mode: "off"; updatedAt: string };

export type WebAuthState =
  | { source: "settings" | "env"; mode: "password"; credential: string }
  | { source: "settings" | "none"; mode: "off"; credential: "" }
  | { source: "settings"; mode: "unreadable"; credential: "" };

// One limiter for every place a password is checked: sign-in, change, turn off.
export const passwordAttempts = new FailedLoginLimiter();

export function webAuthFilePath(env: Record<string, string | undefined> = process.env): string {
  return env.WEB_AUTH_FILE || join(process.cwd(), "data", "web-auth.json");
}

let cache: { path: string; mtimeMs: number; value: StoredWebAuth | "unreadable" } | null = null;

function parse(raw: string): StoredWebAuth | "unreadable" {
  try {
    const value = JSON.parse(raw);
    if (value?.version !== 1) return "unreadable";
    if (value.mode === "off" && typeof value.updatedAt === "string") return value;
    if (
      value.mode === "password" &&
      [value.salt, value.hash, value.sessionSecret, value.updatedAt].every((field) => typeof field === "string" && field)
    ) {
      return value;
    }
  } catch {
    // fall through
  }
  return "unreadable";
}

// null when there is no file. Re-read only when the file changes.
async function readStored(): Promise<StoredWebAuth | "unreadable" | null> {
  const path = webAuthFilePath();
  let mtimeMs: number;
  try {
    mtimeMs = (await stat(path)).mtimeMs;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      cache = null;
      return null;
    }
    return "unreadable";
  }
  if (cache && cache.path === path && cache.mtimeMs === mtimeMs) return cache.value;
  const value = parse(await readFile(path, "utf8").catch(() => ""));
  cache = { path, mtimeMs, value };
  return value;
}

// An unreadable file never falls back to "off": the proxy refuses every request
// until it is fixed or deleted, so a damaged file cannot open the dashboard.
export async function resolveWebAuth(): Promise<WebAuthState> {
  const stored = await readStored();
  if (stored === "unreadable") return { source: "settings", mode: "unreadable", credential: "" };
  if (stored?.mode === "password") {
    return { source: "settings", mode: "password", credential: `${stored.sessionSecret}\0${stored.hash}` };
  }
  if (stored?.mode === "off") return { source: "settings", mode: "off", credential: "" };
  const credential = sessionCredential();
  if (credential) return { source: "env", mode: "password", credential };
  return { source: "none", mode: "off", credential: "" };
}

async function hashPassword(password: string, salt: Buffer): Promise<Buffer> {
  return scrypt(password, salt, KEY_LENGTH);
}

// True when `candidate` is the password currently in force. With sign-in off
// there is no password to match.
export async function verifyWebPassword(candidate: string): Promise<boolean> {
  const stored = await readStored();
  if (stored === "unreadable" || stored?.mode === "off") return false;
  if (stored?.mode === "password") {
    const expected = Buffer.from(stored.hash, "base64");
    const actual = await hashPassword(candidate, Buffer.from(stored.salt, "base64"));
    return expected.length === actual.length && timingSafeEqual(expected, actual);
  }
  return passwordMatches(candidate, configuredWebPassword());
}

async function writeStored(value: StoredWebAuth): Promise<void> {
  const path = webAuthFilePath();
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const tmp = `${path}.${process.pid}.tmp`;
  await writeFile(tmp, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(tmp, path);
  cache = null;
}

export async function storeWebPassword(password: string, now: Date = new Date()): Promise<void> {
  const salt = randomBytes(16);
  const hash = await hashPassword(password, salt);
  await writeStored({
    version: 1,
    mode: "password",
    salt: salt.toString("base64"),
    hash: hash.toString("base64"),
    sessionSecret: randomBytes(32).toString("base64url"),
    updatedAt: now.toISOString(),
  });
}

export async function storeWebSignInOff(now: Date = new Date()): Promise<void> {
  await writeStored({ version: 1, mode: "off", updatedAt: now.toISOString() });
}

// Test helper: forget the cached file between cases.
export async function resetWebAuthStoreForTests(): Promise<void> {
  cache = null;
  await unlink(webAuthFilePath()).catch(() => undefined);
}

export function checkNewWebPassword(next: string, confirm: string): string | null {
  if (next.length < MIN_WEB_PASSWORD_LENGTH) return `Use at least ${MIN_WEB_PASSWORD_LENGTH} characters.`;
  if (next !== next.trim()) return "Remove the spaces at the start or end.";
  if (next !== confirm) return "The two passwords do not match.";
  return null;
}
