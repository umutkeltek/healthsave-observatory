"use client";

import { createContext, type ReactNode, useContext, useRef, useState, useTransition } from "react";

import { setDensityAction } from "../lib/actions";
import { runAction } from "../lib/session";
import type { Density } from "../lib/prefs";
import { useI18n } from "./I18nProvider";

// Optimistic: the UI flips the instant you click; the cookie write settles in
// the background. Never disabled - switching modes must feel like a light
// switch, not a form submit. One owner: the Shell calls this once and shares
// the value (DensityProvider) with the sidebar and the Settings page, so the
// two can never show different modes. The local pick gives way to the server
// value once the server has it, and is dropped if the write failed.
export function useOptimisticDensity(server: Density): [Density, (mode: Density) => void] {
  const [local, setLocal] = useState<Density | null>(null);
  const [, startTransition] = useTransition();
  // Only the newest pick may undo itself on a failed write: an older pick's
  // late failure must not throw away a newer one.
  const latestPick = useRef(0);
  if (local !== null && local === server) setLocal(null);
  const pick = (mode: Density) => {
    const id = ++latestPick.current;
    setLocal(mode);
    startTransition(async () => {
      const result = await runAction(() => setDensityAction(mode));
      if (!result.ok && latestPick.current === id) setLocal(null);
    });
  };
  return [local ?? server, pick];
}

type SharedDensity = { density: Density; pick: (mode: Density) => void };
const DensityContext = createContext<SharedDensity | null>(null);

/** The Shell's density, for every toggle inside it. */
export function DensityProvider({ value, children }: { value: SharedDensity; children: ReactNode }) {
  return <DensityContext.Provider value={value}>{children}</DensityContext.Provider>;
}

export function DensityToggle({
  density,
  onPick,
}: {
  density: Density;
  onPick: (mode: Density) => void;
}) {
  const { dict } = useI18n();
  return (
    <div className="density-toggle" role="group" aria-label={dict.density.label}>
      <button
        type="button"
        className={density === "essentials" ? "active" : ""}
        onClick={() => onPick("essentials")}
      >
        {dict.density.essentials}
      </button>
      <button
        type="button"
        className={density === "observatory" ? "active" : ""}
        onClick={() => onPick("observatory")}
      >
        {dict.density.observatory}
      </button>
    </div>
  );
}

// The Settings page's toggle: the Shell's shared value when inside it (always,
// in the app); its own only where no Shell is mounted.
export function StandaloneDensityToggle({ density }: { density: Density }) {
  const shared = useContext(DensityContext);
  const [own, pickOwn] = useOptimisticDensity(density);
  return <DensityToggle density={shared ? shared.density : own} onPick={shared ? shared.pick : pickOwn} />;
}
