"use client";

import { useEffect, useRef, useState } from "react";

// The recovery dial's luminous fill — the ONLY client piece of the otherwise
// server-rendered gauge (mirrors CountUp's discipline). The arc <path> is drawn
// with pathLength={1}, so stroke-dashoffset speaks in fractions: offset
// `1 - score/100` reveals the score's share of the 0-100 sweep. On SSR, no-JS,
// and reduced-motion it renders the final fill instantly; with motion it sweeps
// up from empty and settles with one small overshoot (~850ms), porting the
// reference mock's easing verbatim.
export function DialFill({
  d,
  score,
  duration = 850,
  delay = 220,
}: {
  d: string;
  score: number;
  duration?: number;
  delay?: number;
}) {
  const frac = Math.max(0, Math.min(100, score)) / 100;
  const finalOffset = 1 - frac;
  const [offset, setOffset] = useState(finalOffset);
  const animated = useRef(false);

  useEffect(() => {
    if (animated.current) {
      setOffset(finalOffset);
      return;
    }
    animated.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setOffset(finalOffset);
      return;
    }
    // Damped settle with a capped 6% overshoot — the mock's dial physics.
    const settle = (p: number) => 1 - Math.exp(-6 * p) * Math.cos(9 * p) * (1 - p * 0.2);
    const t0 = performance.now();
    let raf = 0;
    setOffset(1); // start empty
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0 - delay) / duration);
      if (p >= 0) {
        const e = p < 1 ? settle(p) : 1;
        setOffset(1 - frac * Math.min(1.06, e));
      }
      if (p < 1) raf = requestAnimationFrame(tick);
      else setOffset(finalOffset);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [frac, finalOffset, duration, delay]);

  return (
    <path
      className="body-dial-fill"
      d={d}
      pathLength={1}
      style={{ strokeDasharray: 1, strokeDashoffset: offset }}
    />
  );
}
