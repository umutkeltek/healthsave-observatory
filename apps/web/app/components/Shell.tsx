"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

// Client shell so the sidebar can become a slide-over drawer on small screens.
// On desktop it's a normal fixed sidebar; the menu button + scrim are CSS-hidden.
export function Shell({
  provider,
  isLocal,
  synced,
  children,
}: {
  provider: string;
  isLocal: boolean;
  synced: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`app ${open ? "nav-open" : ""}`}>
      <Sidebar
        provider={provider}
        isLocal={isLocal}
        synced={synced}
        onNavigate={() => setOpen(false)}
      />
      <button
        type="button"
        className="nav-scrim"
        aria-label="Close navigation"
        tabIndex={open ? 0 : -1}
        onClick={() => setOpen(false)}
      />
      <div className="app-main">
        <Topbar
          provider={provider}
          isLocal={isLocal}
          synced={synced}
          onMenu={() => setOpen((v) => !v)}
        />
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
