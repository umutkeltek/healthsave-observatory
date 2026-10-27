// Password login for the Observatory web app. Pure functions on Web Crypto so the
// proxy (proxy.ts), the /auth route handlers and the tests share one definition.
//
// Login is on when WEB_PASSWORD is set (setup generates it for new installs) and
// off when it is empty, so an older .env keeps today's behavior. The session
// cookie is "<expiry ms>.<HMAC-SHA256(expiry)>", keyed from the password: changing
// WEB_PASSWORD signs every browser out, and nothing is stored on the server.

export const SESSION_COOKIE = "hs_session";
export const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

// Set by the proxy on the /login request only, so the root layout renders the
// page without the Observatory shell (whose status widgets read health data).
// The proxy strips any copy a client sends.
export const BARE_LAYOUT_HEADER = "x-healthsave-bare-layout";

const KEY_LABEL = "healthsave-web-session-v1";
const encoder = new TextEncoder();

export function configuredWebPassword(env: Record<string, string | undefined> = process.env): string {
  return (env.WEB_PASSWORD ?? "").trim();
}

function toBase64Url(bytes: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sessionKey(password: string): Promise<CryptoKey> {
  const secret = await crypto.subtle.digest("SHA-256", encoder.encode(`${KEY_LABEL}\0${password}`));
  return crypto.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
}

async function signature(password: string, expiresAt: number): Promise<string> {
  const mac = await crypto.subtle.sign("HMAC", await sessionKey(password), encoder.encode(String(expiresAt)));
  return toBase64Url(mac);
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(password: string, now: number = Date.now()): Promise<string> {
  const expiresAt = now + SESSION_MAX_AGE_SECONDS * 1000;
  return `${expiresAt}.${await signature(password, expiresAt)}`;
}

export async function isValidSessionToken(
  token: string | undefined,
  password: string,
  now: number = Date.now(),
): Promise<boolean> {
  if (!token || !password) return false;
  const dot = token.indexOf(".");
  if (dot <= 0) return false;
  const expiresRaw = token.slice(0, dot);
  if (!/^\d{1,16}$/.test(expiresRaw)) return false;
  const expiresAt = Number(expiresRaw);
  if (expiresAt <= now) return false;
  return constantTimeEqual(token.slice(dot + 1), await signature(password, expiresAt));
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

// Where to go after signing in: a same-origin path only, never "//host" or a URL.
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  if (raw.startsWith("/login") || raw.startsWith("/auth/")) return "/";
  return raw;
}

// Reachable without a session: the sign-in page and its form target, and the
// container healthcheck (a bare "ok", no data). Static assets never reach the
// proxy (see the matcher in proxy.ts).
export function isPublicPath(pathname: string): boolean {
  return pathname === "/login" || pathname === "/auth/login" || pathname === "/api/health";
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
