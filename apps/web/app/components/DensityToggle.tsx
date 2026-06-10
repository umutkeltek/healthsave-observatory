"use client";

import { useState, useTransition } from "react";

import { setDensityAction } from "../lib/actions";
import type { Density } from "../lib/prefs";

// Optimistic: the UI flips the instant you click; the cookie write settles in
// the background. Never disabled — switching modes must feel like a light
// switch, not a form submit. Used by the sidebar (which also reshapes its nav
// from the same optimistic value) and the Settings page.
export function useOptimisticDensity(server: Density): [Density, (mode: Density) => void] {
  const [local, setLocal] = useState<Density | null>(null);
  const [, startTransition] = useTransition();
  const pick = (mode: Density) => {
    setLocal(mode);
    startTransition(() => setDensityAction(mode).then(() => undefined));
  };
  return [local ?? server, pick];
}

export function DensityToggle({
  density,
  onPick,
}: {
  density: Density;
  onPick: (mode: Density) => void;
}) {
  return (
    <div className="density-toggle" role="group" aria-label="View mode">
      <button
        type="button"
        className={density === "essentials" ? "active" : ""}
        onClick={() => onPick("essentials")}
      >
        Essentials
      </button>
      <button
        type="button"
        className={density === "observatory" ? "active" : ""}
        onClick={() => onPick("observatory")}
      >
        Observatory
      </button>
    </div>
  );
}

// Self-contained variant for pages outside the sidebar's state scope.
export function StandaloneDensityToggle({ density }: { density: Density }) {
  const [shown, pick] = useOptimisticDensity(density);
  return <DensityToggle density={shown} onPick={pick} />;
}
