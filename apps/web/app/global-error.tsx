"use client";

// Last-resort boundary: catches throws in the root layout/shell itself, where
// app/error.tsx can't help. Must render its own <html>/<body>.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" data-theme="dark">
      <body>
        <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", fontFamily: "system-ui" }}>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <h1 style={{ fontSize: 18 }}>HealthSave Observatory hit a UI error</h1>
            <p style={{ opacity: 0.7, fontSize: 14 }}>
              Your data is untouched.{error.digest ? ` Ref ${error.digest}.` : ""}
            </p>
            <button
              type="button"
              onClick={() => reset()}
              style={{ padding: "8px 16px", borderRadius: 8, cursor: "pointer" }}
            >
              Reload
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
