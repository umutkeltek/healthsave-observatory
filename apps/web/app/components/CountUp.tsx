"use client";

import { useEffect, useRef, useState } from "react";

// Animated number: SSR (and no-JS, and reduced-motion) renders the final
// value; with JS the first mount eases up from zero over the chart-draw
// duration so the hero score and metric values land with the traces.
export function CountUp({ value, duration = 900 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(value);
  const animated = useRef(false);

  useEffect(() => {
    if (animated.current) {
      setDisplay(value);
      return;
    }
    animated.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(value);
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - (1 - p) ** 3;
      setDisplay(Math.round(value * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return <>{display}</>;
}
