"use client";

// Route-level error boundary: a render-time throw degrades to a calm retry
// card inside the shell instead of a white screen. Data-fetch failures never
// reach here (safe* loaders return null); this catches genuine render bugs.
export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="lead">
      <div className="card">
        <div className="hero-eyebrow">Something broke</div>
        <p className="empty" style={{ marginTop: 8 }}>
          This view hit a rendering error. Your data is untouched — this is a UI bug, not a data
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
