"use client";

import { isSignInRequired, signInPath } from "./lib/session";

// Route-level error boundary: a render-time throw degrades to a calm retry
// card inside the shell instead of a white screen. Data-fetch failures never
// reach here (safe* loaders return null); this catches genuine render bugs -
// and an action the proxy refused because the session ended, which is not a
// bug and gets a way to sign in again instead.
export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  if (isSignInRequired(error)) {
    const next = typeof window === "undefined" ? "/" : `${window.location.pathname}${window.location.search}`;
    return (
      <section className="lead">
        <div className="card">
          <div className="hero-eyebrow">Signed out</div>
          <p className="empty" style={{ marginTop: 8 }}>
            Your session has ended, so this change was not saved. Your data is untouched.
          </p>
          <div className="exp-action">
            <a className="btn" href={signInPath(next)}>
              Sign in again
            </a>
          </div>
        </div>
      </section>
    );
  }
  return (
    <section className="lead">
      <div className="card">
        <div className="hero-eyebrow">Something broke</div>
        <p className="empty" style={{ marginTop: 8 }}>
          This view hit a rendering error. Your data is untouched. This is a UI bug, not a data
          problem.{error.digest ? ` (ref ${error.digest})` : ""}
        </p>
        <div className="exp-action">
          <button type="button" className="btn" onClick={() => reset()}>
            Try again
          </button>
        </div>
      </div>
    </section>
  );
}
