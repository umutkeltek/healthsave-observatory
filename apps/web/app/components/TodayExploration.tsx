"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import {
  DEFAULT_TODAY_METRICS,
  todaySelection,
  todaySelectionUrl,
  type TodayRange,
} from "../lib/todayPresentation";

const Exploration = createContext<{
  selectedId: string;
  range: TodayRange;
  select: (id: string, focusDetail?: boolean) => void;
  setRange: (range: TodayRange) => void;
  registerDetail: (node: HTMLElement | null) => void;
} | null>(null);

export function TodayExploration({
  enabled,
  initialMetricId = "vital.hrv_sdnn",
  metricIds = DEFAULT_TODAY_METRICS.map((metric) => metric.id),
  children,
}: {
  enabled: boolean;
  initialMetricId?: string;
  metricIds?: string[];
  children: ReactNode;
}) {
  const params = useSearchParams();
  const { selectedId, range } = todaySelection(
    params,
    metricIds,
    initialMetricId,
  );
  const detail = useRef<HTMLElement | null>(null);
  const focusPending = useRef(false);
  const focusDetail = useCallback(() => {
    if (!focusPending.current || !detail.current) return;
    focusPending.current = false;
    detail.current.focus({ preventScroll: true });
    detail.current.scrollIntoView({
      block: "start",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }, []);
  const registerDetail = useCallback(
    (node: HTMLElement | null) => {
      detail.current = node;
      // A tile can be selected before the streamed chart has mounted.
      if (node) focusDetail();
    },
    [focusDetail],
  );
  useEffect(focusDetail, [selectedId, focusDetail]);

  function update(id: string, days: TodayRange) {
    const next = todaySelectionUrl(window.location.href, id, days);
    if (
      next !==
      `${window.location.pathname}${window.location.search}${window.location.hash}`
    ) {
      // Next integrates the native history API with useSearchParams. No refetch
      // is needed: the chart already has both windows. Back restores selection.
      window.history.pushState(null, "", next);
    }
  }
  function select(id: string, moveFocus = false) {
    if (!metricIds.includes(id)) return;
    focusPending.current = moveFocus;
    update(id, range);
    if (id === selectedId) focusDetail();
  }
  return (
    <Exploration.Provider
      value={
        enabled
          ? {
              selectedId,
              range,
              select,
              setRange: (days) => update(selectedId, days),
              registerDetail,
            }
          : null
      }
    >
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
      onClick={() => exploration.select(id, true)}
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
