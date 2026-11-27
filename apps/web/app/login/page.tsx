import type { Metadata } from "next";
import { cookies } from "next/headers";

import { SignInSubmit } from "../components/SignInSubmit";
import { getDictionary, LOCALE_COOKIE, type Locale, resolveAvailableLocale, signInBlockedMessage } from "../lib/i18n";
import { safeNextPath } from "../lib/webAuth";

export const dynamic = "force-dynamic";

// The interface language, read the way lib/i18n.server.ts does (that module is
// server-only, which this page's tests cannot load).
async function interfaceLocale(): Promise<Locale> {
  const jar = await cookies();
  return resolveAvailableLocale(jar.get(LOCALE_COOKIE)?.value, process.env.HEALTHSAVE_EXPERIMENTAL_LOCALES === "1");
}

export async function generateMetadata(): Promise<Metadata> {
  const dict = getDictionary(await interfaceLocale());
  return { title: `${dict.signIn.pageTitle} · HealthSave Observatory` };
}

// Rendered without the Observatory shell (the proxy marks this request bare), so
// nothing on this page reads health data. The form posts to /auth/login.
// Why the last sign-in did not work, from /auth/login's redirect: "locked" is
// this address's wrong-password limit, "paused" the process-wide ceiling (both
// with `wait`, the seconds until a check runs again); anything else set is a
// wrong password.
type LoginError = { kind: "wrong" } | { kind: "locked" | "paused"; waitSeconds: number | null } | null;

function parseLoginError(raw: string | undefined, wait: string | undefined): LoginError {
  if (!raw) return null;
  if (raw !== "locked" && raw !== "paused") return { kind: "wrong" };
  const seconds = Number(wait);
  const waitSeconds = /^\d{1,4}$/.test(wait ?? "") && seconds >= 1 && seconds <= 3600 ? seconds : null;
  return { kind: raw, waitSeconds };
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string; wait?: string }>;
}) {
  const [{ next, error, wait }, locale] = await Promise.all([searchParams, interfaceLocale()]);
  const dict = getDictionary(locale);
  const loginError = parseLoginError(error, wait);
  return (
    <main className="signin">
      <form className="card" method="post" action="/auth/login">
        <h2>HealthSave Observatory</h2>
        <p className="empty">{dict.signIn.prompt}</p>
        {loginError ? (
          <p className="signin-error" role="alert">
            {loginError.kind === "wrong"
              ? dict.signIn.wrong
              : signInBlockedMessage(
                  dict,
                  loginError.kind === "paused" ? "everyone" : "client",
                  loginError.waitSeconds,
                )}
          </p>
        ) : null}
        <input type="hidden" name="next" value={safeNextPath(next)} />
        <label className="field">
          <span className="field-label">{dict.signIn.password}</span>
          <input
            className="field-input"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            autoFocus
          />
          <span className="field-hint">{dict.signIn.hint}</span>
        </label>
        <SignInSubmit>{dict.signIn.submit}</SignInSubmit>
      </form>
    </main>
  );
}
