import type { Metadata } from "next";

import { safeNextPath } from "../lib/webAuth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sign in · HealthSave Observatory" };

// Rendered without the Observatory shell (the proxy marks this request bare), so
// nothing on this page reads health data. The form posts to /auth/login.
// Why the last sign-in did not work, from /auth/login's redirect. "locked" is
// the shared wrong-password limiter; anything else set is a wrong password.
type LoginError = "wrong" | "locked" | null;

function parseLoginError(raw: string | undefined): LoginError {
  if (!raw) return null;
  return raw === "locked" ? "locked" : "wrong";
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  const loginError = parseLoginError(error);
  return (
    <main className="signin">
      <form className="card" method="post" action="/auth/login">
        <h2>HealthSave Observatory</h2>
        <p className="empty">Enter the web password for this Observatory.</p>
        {loginError ? (
          <p className="signin-error" role="alert">
            {loginError === "locked"
              ? "Too many wrong passwords. Wait a minute and try again."
              : "That password is not right."}
          </p>
        ) : null}
        <input type="hidden" name="next" value={safeNextPath(next)} />
        <label className="field">
          <span className="field-label">Password</span>
          <input
            className="field-input"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            autoFocus
          />
          <span className="field-hint">
            It is WEB_PASSWORD in the .env file on the machine that runs the Observatory.
          </span>
        </label>
        <button className="btn" type="submit">
          Sign in
        </button>
      </form>
    </main>
  );
}
