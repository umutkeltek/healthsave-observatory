"use client";

import Link from "next/link";
import { createContext, useContext, useState, type ReactNode } from "react";

const Exploration = createContext<{
  selectedId: string;
  select: (id: string) => void;
} | null>(null);

export function TodayExploration({
  enabled,
  initialMetricId = "vital.hrv_sdnn",
  children,
}: {
  enabled: boolean;
  initialMetricId?: string;
  children: ReactNode;
}) {
  const [selectedId, setSelectedId] = useState(initialMetricId);
  function select(id: string) {
    setSelectedId(id);
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    document.getElementById("today-reading-detail")?.scrollIntoView({
      block: "nearest",
      behavior: reduceMotion ? "instant" : "smooth",
    });
  }
  return (
    <Exploration.Provider value={enabled ? { selectedId, select } : null}>
      {children}
    </Exploration.Provider>
  );
}

export function useTodayExploration() {
  return useContext(Exploration);
}

export function TodayReadingTile({
  id,
  title,
  className,
  children,
  readingLabel,
}: {
  id: string;
  title: string;
  className: string;
  children: ReactNode;
  readingLabel?: string;
}) {
  const exploration = useTodayExploration();
  return exploration ? (
    <button
      type="button"
      className={className}
      aria-label={`Explore ${title}${readingLabel ? `: ${readingLabel}` : ""}`}
      aria-pressed={exploration.selectedId === id}
      aria-controls="today-reading-detail"
      onClick={() => exploration.select(id)}
    >
      {children}
    </button>
  ) : (
    <Link
      href={
        id === "sleep.duration"
          ? "/sleep"
          : `/library/${encodeURIComponent(id)}`
      }
      className={className}
    >
      {children}
    </Link>
  );
}

export function TodayTileAffordance() {
  const exploration = useTodayExploration();
  return <span aria-hidden>{exploration ? "↓" : "↗"}</span>;
}
