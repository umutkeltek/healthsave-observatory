// Password login for the Observatory web app. Pure functions on Web Crypto so the
// proxy (proxy.ts), the /auth route handlers, server actions and the tests share
// one definition.
//
// Login is on when WEB_PASSWORD is set (setup generates it for new installs) and
// off when it is empty, so an older .env keeps today's behavior. The session
// cookie is "<expiry ms>.<HMAC-SHA256(expiry)>". The HMAC key comes from
// WEB_SESSION_SECRET plus the password: a captured cookie cannot be cracked back
// to the password, and changing either value signs every browser out. Nothing is
// stored on the server.

export const SESSION_COOKIE = "hs_session";
export const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

// Set by the proxy on GET /login only, so the root layout renders the page
// without the Observatory shell (whose status widgets read health data). The
// proxy strips any copy a client sends.
export const BARE_LAYOUT_HEADER = "x-healthsave-bare-layout";

const KEY_LABEL = "healthsave-web-session-v2";
const encoder = new TextEncoder();

type Env = Record<string, string | undefined>;

export function configuredWebPassword(env: Env = process.env): string {
  return (env.WEB_PASSWORD ?? "").trim();
}

// What session cookies are signed with. Empty when login is off.
export function sessionCredential(env: Env = process.env): string {
  const password = configuredWebPassword(env);
  if (!password) return "";
  return `${(env.WEB_SESSION_SECRET ?? "").trim()}\0${password}`;
}

function toBase64Url(bytes: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sessionKey(credential: string): Promise<CryptoKey> {
  const secret = await crypto.subtle.digest("SHA-256", encoder.encode(`${KEY_LABEL}\0${credential}`));
  return crypto.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}

async function signature(credential: string, expiresAt: number): Promise<string> {
  const mac = await crypto.subtle.sign("HMAC", await sessionKey(credential), encoder.encode(String(expiresAt)));
  return toBase64Url(mac);
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(credential: string, now: number = Date.now()): Promise<string> {
  const expiresAt = now + SESSION_MAX_AGE_SECONDS * 1000;
  return `${expiresAt}.${await signature(credential, expiresAt)}`;
}

export async function isValidSessionToken(
  token: string | undefined,
  credential: string,
  now: number = Date.now(),
): Promise<boolean> {
  if (!token || !credential) return false;
  const dot = token.indexOf(".");
  if (dot <= 0) return false;
  const expiresRaw = token.slice(0, dot);
  if (!/^\d{1,16}$/.test(expiresRaw)) return false;
  const expiresAt = Number(expiresRaw);
  if (expiresAt <= now) return false;
  return constantTimeEqual(token.slice(dot + 1), await signature(credential, expiresAt));
}

// Compares SHA-256 digests so the time taken does not depend on where the
// typed password first differs, or on its length.
export async function passwordMatches(candidate: string, password: string): Promise<boolean> {
  if (!password) return false;
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(candidate)),
    crypto.subtle.digest("SHA-256", encoder.encode(password)),
  ]);
  return constantTimeEqual(toBase64Url(a), toBase64Url(b));
}

// Where to go after signing in: a path on this site only. Control characters and
// backslashes are refused outright, because browsers drop tabs and newlines from
// a Location header ("/\t/evil.example" becomes "//evil.example") and read "\"
// as "/". What is left must parse back to the same origin.
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || /[\u0000-\u001f\u007f\\]/.test(raw)) return "/";
  let parsed: URL;
  try {
    parsed = new URL(raw, "http://next.invalid");
  } catch {
    return "/";
  }
  if (parsed.origin !== "http://next.invalid") return "/";
  const path = `${parsed.pathname}${parsed.search}`;
  if (path.startsWith("//") || path === "/login" || path.startsWith("/login?") || path.startsWith("/auth/")) {
    return "/";
  }
  return path;
}

// Reachable without a session: the sign-in page (GET only, so its server actions
// stay behind the session check), its form target, the container healthcheck (a
// bare "ok") and the app icon. Static build assets skip the proxy entirely.
export function isPublicRequest(pathname: string, method: string): boolean {
  const read = method === "GET" || method === "HEAD";
  if (pathname === "/login") return read;
  if (pathname === "/auth/login") return method === "POST";
  return read && (pathname === "/api/health" || pathname === "/icon.svg");
}

// Form posts to /auth/* must come from this site's own pages. Browsers send
// Sec-Fetch-Site (or at least Origin) on every POST; a request with neither is
// not a browser, so a cross-site page cannot have caused it.
export function isSameOriginPost(headers: Headers): boolean {
  const site = headers.get("sec-fetch-site");
  if (site) return site === "same-origin";
  const origin = headers.get("origin");
  if (!origin) return true;
  const host = headers.get("x-forwarded-host") ?? headers.get("host");
  try {
    return Boolean(host) && new URL(origin).host === host;
  } catch {
    return false;
  }
}

// Redirect with a relative Location. Behind Docker or a LAN address, request.url
// can carry the server's own hostname ("localhost") instead of the one the
// browser used, so an absolute redirect built from it sends people elsewhere.
export function relativeRedirect(path: string, status: 303 | 307 = 303): ResponseInit {
  return { status, headers: { location: path, "cache-control": "no-store" } };
}

export function sessionCookieOptions(secure: boolean, maxAge: number = SESSION_MAX_AGE_SECONDS) {
  return { httpOnly: true, sameSite: "lax" as const, secure, path: "/", maxAge };
}

// The Secure flag only when the browser reached us over HTTPS (directly or via a
// TLS-terminating proxy): on a plain-HTTP LAN a Secure cookie would never be sent.
export function requestIsHttps(url: URL, forwardedProto: string | null): boolean {
  if (forwardedProto) return forwardedProto.split(",")[0].trim().toLowerCase() === "https";
  return url.protocol === "https:";
}

// Wrong-password limiter. Each bucket allows FAILED_LOGIN_LIMIT misses inside
// FAILED_LOGIN_WINDOW_MS; past that, sign-in sends the browser back to
// /login?error=locked (with how long to wait) without a check until the window
// moves on. By default every request shares one bucket. Behind a trusted proxy
// (WEB_TRUST_PROXY, see clientAddress) each client address gets its own, so
// guesses from one place cannot lock the owner out from another, and a
// process-wide ceiling (FAILED_LOGIN_GLOBAL_LIMIT) still pauses sign-in for
// everyone during a flood over many addresses. Generated passwords are far out
// of reach anyway; this is for passwords a person picks.
export const FAILED_LOGIN_LIMIT = 10;
export const FAILED_LOGIN_GLOBAL_LIMIT = 30;
export const FAILED_LOGIN_WINDOW_MS = 60_000;
export const MAX_TRACKED_LOGIN_CLIENTS = 1024;

export type LoginBlock = {
  // "client": this address made too many guesses. "everyone": too many guesses
  // overall, so sign-in is paused for every address.
  scope: "client" | "everyone";
  retryAfterSeconds: number;
};

// Whether a reverse proxy the operator trusts sits in front of the web port and
// writes X-Forwarded-For (WEB_TRUST_PROXY=true). Off by default: with the port
// reachable directly, those headers come from the client and can name any
// address, so they must not decide whose bucket a guess counts against.
export function trustsProxyHeaders(env: Env = process.env): boolean {
  return ["1", "true", "yes"].includes((env.WEB_TRUST_PROXY ?? "").trim().toLowerCase());
}

// The client address the limiter keys on, or null for the one shared bucket.
// Only behind a trusted proxy (trustsProxyHeaders): then the last
// X-Forwarded-For entry is the address that proxy saw (it appends it; anything
// to its left came from the client), else X-Real-IP. Without one, always null:
// every request shares one bucket at FAILED_LOGIN_LIMIT, the old behaviour.
export function clientAddress(headers: Headers, env: Env = process.env): string | null {
  if (!trustsProxyHeaders(env)) return null;
  const forwarded = (headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (forwarded.length > 0) return forwarded[forwarded.length - 1].slice(0, 100);
  const real = (headers.get("x-real-ip") ?? "").trim();
  return real ? real.slice(0, 100) : null;
}

// Durations use the monotonic clock: a wall clock stepping back (VM resume, NTP)
// must not keep an address blocked for as long as the step.
const monotonic = () => performance.now();
const NO_ADDRESS = "";

export class FailedLoginLimiter {
  private readonly limit: number;
  private readonly windowMs: number;
  private readonly globalLimit: number;
  private readonly maxClients: number;
  private readonly clients = new Map<string, number[]>();
  private all: number[] = [];

  constructor({
    limit = FAILED_LOGIN_LIMIT,
    windowMs = FAILED_LOGIN_WINDOW_MS,
    globalLimit = FAILED_LOGIN_GLOBAL_LIMIT,
    maxClients = MAX_TRACKED_LOGIN_CLIENTS,
  }: { limit?: number; windowMs?: number; globalLimit?: number; maxClients?: number } = {}) {
    this.limit = limit;
    this.windowMs = windowMs;
    this.globalLimit = globalLimit;
    this.maxClients = maxClients;
  }

  private recent(failures: number[], now: number): number[] {
    const cutoff = now - this.windowMs;
    let first = 0;
    while (first < failures.length && failures[first] <= cutoff) first++;
    return first === 0 ? failures : failures.slice(first);
  }

  // Seconds until fewer than `limit` of these failures are inside the window.
  private wait(failures: number[], limit: number, now: number): number {
    const oldestCounted = failures[failures.length - limit];
    return Math.max(1, Math.ceil((oldestCounted + this.windowMs - now) / 1000));
  }

  /** Why a check for this address must not run now, or null when it may. */
  blocked(client: string | null, now: number = monotonic()): LoginBlock | null {
    this.all = this.recent(this.all, now);
    const key = client ?? NO_ADDRESS;
    const mine = this.recent(this.clients.get(key) ?? [], now);
    if (mine.length === 0) this.clients.delete(key);
    else this.clients.set(key, mine);

    let block: LoginBlock | null = null;
    if (mine.length >= this.limit) {
      block = { scope: "client", retryAfterSeconds: this.wait(mine, this.limit, now) };
    }
    if (this.all.length >= this.globalLimit) {
      const everyone = this.wait(this.all, this.globalLimit, now);
      if (!block || everyone > block.retryAfterSeconds) block = { scope: "everyone", retryAfterSeconds: everyone };
    }
    return block;
  }

  /**
   * Counts one failure for this address and returns its stamp. Callers count an
   * attempt BEFORE checking the password and forgive it on a match, so guesses
   * sent all at once cannot each be checked before the first one is counted.
   */
  recordFailure(client: string | null, now: number = monotonic()): number {
    const key = client ?? NO_ADDRESS;
    const mine = this.recent(this.clients.get(key) ?? [], now);
    // Most recently failed last (a Map keeps insertion order), so the bound
    // below forgets the address that has been quiet longest.
    this.clients.delete(key);
    this.clients.set(key, [...mine, now]);
    this.all = [...this.recent(this.all, now), now];
    for (const [stale] of this.clients) {
      if (this.clients.size <= this.maxClients) break;
      this.clients.delete(stale);
    }
    return now;
  }

  /** Takes back one counted attempt (the password matched). */
  forgive(client: string | null, stamp: number) {
    const key = client ?? NO_ADDRESS;
    const mine = this.clients.get(key);
    const at = mine?.indexOf(stamp) ?? -1;
    if (mine && at >= 0) {
      const rest = [...mine.slice(0, at), ...mine.slice(at + 1)];
      if (rest.length === 0) this.clients.delete(key);
      else this.clients.set(key, rest);
    }
    const inAll = this.all.indexOf(stamp);
    if (inAll >= 0) this.all = [...this.all.slice(0, inAll), ...this.all.slice(inAll + 1)];
  }

  trackedClients(): number {
    return this.clients.size;
  }

  // Test seam: forget every failure.
  reset() {
    this.clients.clear();
    this.all = [];
  }
}
