"use client";

import "./globals.css";

type ThemeStorage = Pick<Storage, "getItem">;

// The theme the person chose (ThemeToggle stores it), light by default: the
// same rule as the layout's pre-paint script.
export function savedTheme(storage: ThemeStorage | undefined): "light" | "dark" {
  try {
    return storage?.getItem("theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function browserStorage(): ThemeStorage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

// Last-resort boundary: catches throws in the root layout/shell itself, where
// app/error.tsx can't help. Must render its own <html>/<body>. It uses the
// sign-in page's standalone card, so it keeps the one design language.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" data-theme={savedTheme(browserStorage())} suppressHydrationWarning>
      <body>
        <main className="signin">
          <div className="card">
            <h2>HealthSave Observatory hit a UI error</h2>
            <p className="empty">Your data is untouched.{error.digest ? ` Ref ${error.digest}.` : ""}</p>
            <button type="button" className="btn" onClick={() => reset()}>
              Reload
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
