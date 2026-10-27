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

// Wrong-password limiter for the whole process: after FAILED_LOGIN_LIMIT misses
// inside FAILED_LOGIN_WINDOW_MS, sign-in answers 429 without checking until the
// window moves on. Generated passwords are far out of reach anyway; this is for
// passwords a person picks.
export const FAILED_LOGIN_LIMIT = 10;
export const FAILED_LOGIN_WINDOW_MS = 60_000;

export class FailedLoginLimiter {
  private failures: number[] = [];

  constructor(
    private readonly limit = FAILED_LOGIN_LIMIT,
    private readonly windowMs = FAILED_LOGIN_WINDOW_MS,
  ) {}

  private prune(now: number) {
    const cutoff = now - this.windowMs;
    while (this.failures.length > 0 && this.failures[0] <= cutoff) this.failures.shift();
  }

  isBlocked(now: number = Date.now()): boolean {
    this.prune(now);
    return this.failures.length >= this.limit;
  }

  recordFailure(now: number = Date.now()) {
    this.prune(now);
    this.failures.push(now);
  }
}
