import type { Metadata } from "next";

import { safeNextPath } from "../lib/webAuth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sign in · HealthSave Observatory" };

// Rendered without the Observatory shell (the proxy marks this request bare), so
// nothing on this page reads health data. The form posts to /auth/login.
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  return (
    <main className="signin">
      <form className="card" method="post" action="/auth/login">
        <h2>HealthSave Observatory</h2>
        <p className="empty">Enter the web password for this Observatory.</p>
        {error ? (
          <p className="signin-error" role="alert">
            That password is not right.
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
