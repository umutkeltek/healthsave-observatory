"use client";

import { useEffect, useState } from "react";

type Theme = "dark" | "light";

// Toggles the data-theme on <html> and persists it. The no-flash inline script
// in layout.tsx applies the saved theme before paint; this just flips it.
export function ThemeToggle() {
 const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const current = document.documentElement.dataset.theme;
    setTheme(current === "light" ? "light" : "dark");
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // private mode / storage disabled - the toggle still works for the session
    }
    setTheme(next);
  }

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      title="Toggle theme"
    >
      {/* Both icons render; CSS picks one from <html data-theme>, which the
          no-flash script sets before paint. Picking from state showed the
          moon in dark mode until hydration (seconds on a slow network). */}
      <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <g className="theme-icon-sun">
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1" />
        </g>
        <g className="theme-icon-moon">
          <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z" />
        </g>
      </svg>
    </button>
  );
}
