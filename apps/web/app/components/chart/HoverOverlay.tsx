"use client";

import { useCallback, useRef, useState } from "react";

// The ONE client-side chart piece: an absolutely-positioned layer that adds a
// crosshair + tooltip to any server-rendered chart. Charts stay server
// components and pass pre-computed point positions (percentages of the plot
// box); this never re-derives chart math.
export type HoverPoint = {
  xPct: number; // 0–100, position within the plot box
  yPct: number;
  label: string; // e.g. the reading's date
  value: string; // pre-formatted value + unit
  source?: string | null;
};

export function HoverOverlay({ points }: { points: HoverPoint[] }) {
  const box = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<HoverPoint | null>(null);

  const onMove = useCallback(
    (event: React.PointerEvent) => {
      const el = box.current;
      if (!el || points.length === 0) return;
      const rect = el.getBoundingClientRect();
      const xPct = ((event.clientX - rect.left) / rect.width) * 100;
      let nearest = points[0];
      let best = Number.POSITIVE_INFINITY;
      for (const point of points) {
        const d = Math.abs(point.xPct - xPct);
        if (d < best) {
          best = d;
          nearest = point;
        }
      }
      setActive(nearest);
    },
    [points],
  );

  if (points.length === 0) return null;

  return (
    <div
      ref={box}
      className="hover-overlay"
      onPointerMove={onMove}
      onPointerLeave={() => setActive(null)}
    >
      {active && (
        <>
          <div className="hover-crosshair" style={{ left: `${active.xPct}%` }} />
          <div className="hover-dot" style={{ left: `${active.xPct}%`, top: `${active.yPct}%` }} />
          <div
            className="hover-tip mono"
            style={{
              left: `${active.xPct}%`,
              transform: active.xPct > 70 ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
            }}
          >
            <span className="hover-tip-value">{active.value}</span>
            <span className="hover-tip-label">{active.label}</span>
            {active.source && <span className="hover-tip-source">{active.source}</span>}
          </div>
        </>
      )}
    </div>
  );
}
