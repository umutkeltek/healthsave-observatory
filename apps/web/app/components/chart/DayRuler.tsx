"use client";

// The day ruler: one client piece that reads a per-day chart. The chart stays
// server-rendered (BaselineRibbon does the math and hands ScrubCursor its
// point positions); this file only holds which day is selected and whether a
// drag is in progress.
//
//   <DayScrub series={...}>        selected day + drag state; marks the scope
//     ...chart with <ScrubCursor>  stem, dot and glow on the selected day
//     <DayRuler label="..." />     the slider: ticks, handle, lens
//     <ScrubAnswer />              one answer line, value in ink
//   </DayScrub>
//
// While a drag is held the scope carries data-scrubbing, and anything marked
// .scrub-soft blurs back (CSS). The data itself (ScrubSeries) is plain and
// serializable, so a server page can build it.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { scrubAnswer, scrubValueText, type ScrubSeries } from "./dayScrub";

type Scrub = {
  series: ScrubSeries;
  index: number;
  dragging: boolean;
  select: (index: number) => void;
  setDragging: (dragging: boolean) => void;
};

const ScrubContext = createContext<Scrub | null>(null);

export function DayScrub({
  series,
  className,
  children,
}: {
  series: ScrubSeries;
  className?: string;
  children: ReactNode;
}) {
  const last = series.days.length - 1;
  const [index, setIndex] = useState(series.initial);
  const [dragging, setDragging] = useState(false);
  const select = useCallback(
    (next: number) => setIndex(Math.min(last, Math.max(0, Math.round(next)))),
    [last],
  );
  return (
    <ScrubContext.Provider
      value={{ series, index: Math.min(index, last), dragging, select, setDragging }}
    >
      <div
        className={className ? `day-scrub ${className}` : "day-scrub"}
        data-scrubbing={dragging ? "" : undefined}
      >
        {children}
      </div>
    </ScrubContext.Provider>
  );
}

const LENS_W = 128; // px
const MAGNIFY = 1.5;
const OVERHANG = 12; // handle and lens may pass the ruler's ends by this much
const GROW = 0.45; // ticks near the pointer grow by up to 45%

const frac = (index: number, count: number) => (count > 1 ? index / (count - 1) : 0.5);

export function DayRuler({ label }: { label: string }) {
  const scrub = useContext(ScrubContext);
  const root = useRef<HTMLDivElement>(null);
  // A mouse or pen press takes the handle at once. A finger waits until it
  // has clearly moved sideways, so a vertical swipe that starts on the ruler
  // still scrolls the page and leaves the selected day alone; a tap selects.
  const press = useRef<{ x: number; y: number; touch: boolean; active: boolean } | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (!scrub || scrub.series.days.length === 0) return null;
  const { series, index, dragging, select, setDragging } = scrub;
  const days = series.days;
  const count = days.length;
  const day = days[index];
  const big = 7;

  const at = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const f = box.width > 0 ? (event.clientX - box.left) / box.width : 0;
    return Math.min(1, Math.max(0, f)) * (count - 1);
  };
  const end = () => {
    const was = press.current?.active;
    press.current = null;
    if (was) setDragging(false);
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Synthetic or already-released pointers cannot be captured; dragging
      // still works while the pointer stays over the ruler.
    }
    const touch = event.pointerType === "touch";
    press.current = { x: event.clientX, y: event.clientY, touch, active: !touch };
    if (touch) return;
    setDragging(true);
    select(at(event));
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const held = press.current;
    if (!held) return;
    if (!held.active) {
      const dx = Math.abs(event.clientX - held.x);
      if (dx < 6 || dx <= Math.abs(event.clientY - held.y)) return;
      held.active = true;
      setDragging(true);
    }
    select(at(event));
  };
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (press.current && !press.current.active) select(at(event)); // a tap
    end();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? big : 1;
    const moves: Record<string, number> = {
      ArrowLeft: -step,
      ArrowDown: -step,
      ArrowRight: step,
      ArrowUp: step,
      PageDown: -big,
      PageUp: big,
    };
    if (event.key in moves) select(index + moves[event.key]);
    else if (event.key === "Home") select(0);
    else if (event.key === "End") select(count - 1);
    else return;
    event.preventDefault();
  };

  // Pixel geometry for the lens; the handle itself is positioned in CSS from
  // --f so it sits right before hydration too.
  const x = frac(index, count) * width;
  // At the ends the handle slides inward rather than past the card's edge.
  const pill = day.short ?? "–";
  const half = Math.max(40, 16 + pill.length * 7.2) / 2;
  const nudge =
    width > 0 ? Math.min(Math.max(x, half - OVERHANG), width - half + OVERHANG) - x : 0;
  const lx = Math.min(
    Math.max(x, LENS_W / 2 - OVERHANG),
    Math.max(LENS_W / 2 - OVERHANG, width - LENS_W / 2 + OVERHANG),
  );
  const pitch = count > 1 ? width / (count - 1) : width;
  // The magnified strip, shifted so the selected tick sits under the handle.
  const strip = {
    width: width * MAGNIFY,
    transform: `translateX(${(LENS_W / 2 + (x - lx) - x * MAGNIFY).toFixed(1)}px)`,
  };
  const tickClass = (i: number) => {
    const d = days[i];
    const kind = d.exact === null ? "is-dot" : d.weekStart ? "is-maj" : "is-mid";
    return `day-ruler-tick ${kind}${i <= index ? " is-on" : ""}`;
  };
  const ticks = (grow: boolean) =>
    days.map((d, i) => {
      const distance = (i - index) * pitch;
      const style = {
        left: `${frac(i, count) * 100}%`,
        "--s": grow && dragging ? (1 + GROW * Math.exp(-(distance * distance) / 1800)).toFixed(3) : "1",
      } as CSSProperties;
      return <i key={d.date} className={tickClass(i)} style={style} />;
    });

  return (
    <div className="day-ruler-wrap">
      <div
        ref={root}
        className={dragging ? "day-ruler is-dragging" : "day-ruler"}
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={count - 1}
        aria-valuenow={index}
        aria-valuetext={scrubValueText(day, series.unit)}
        style={{ "--f": frac(index, count) } as CSSProperties}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={end}
        onLostPointerCapture={end}
        onKeyDown={onKeyDown}
      >
        <div className="day-ruler-ticks" aria-hidden>
          {ticks(true)}
        </div>
        <div className="day-ruler-at" aria-hidden style={{ "--nudge": `${nudge.toFixed(1)}px` } as CSSProperties}>
          <span className="day-ruler-pill">{pill}</span>
        </div>
        <div
          className="day-ruler-lens"
          aria-hidden
          style={
            {
              width: LENS_W,
              transform: `translateX(${(lx - LENS_W / 2).toFixed(1)}px)`,
              "--origin": `${(LENS_W / 2 + x - lx).toFixed(1)}px`,
            } as CSSProperties
          }
        >
          <div className="day-ruler-lens-face">
            <span className="day-ruler-lens-value">
              <b>{day.exact ?? "No reading"}</b>
              {day.exact !== null && series.unit ? <span>{series.unit}</span> : null}
            </span>
            {/* Sharp magnified ticks in the middle; at the lens's edges the
                same ticks with a warm and a cool fringe, as glass bends them. */}
            {["day-ruler-lens-ticks", "day-ruler-lens-ticks is-fringe"].map((name) => (
              <span key={name} className={name}>
                <span className="day-ruler-strip" style={strip}>
                  {ticks(false)}
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>
      <div className="day-ruler-axis" aria-hidden>
        {days.map((d, i) => {
          if (!d.tick) return null;
          const f = frac(i, count);
          return (
            <span
              key={d.date}
              className={f > 0.93 ? "is-end" : f < 0.07 ? "is-start" : undefined}
              style={{ left: `${f * 100}%` }}
            >
              {d.tick}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function ScrubAnswer({ className }: { className?: string }) {
  const scrub = useContext(ScrubContext);
  if (!scrub || scrub.series.days.length === 0) return null;
  const answer = scrubAnswer(scrub.series.days[scrub.index], scrub.series);
  return (
    <p className={className ? `scrub-answer ${className}` : "scrub-answer"}>
      <b>{answer.value}</b>
      {answer.rest}
    </p>
  );
}

// Positions are percentages of the plot box, computed by the chart.
export type ScrubPoint = { x: number; y: number | null };

export function ScrubCursor({ points }: { points: ScrubPoint[] }) {
  const scrub = useContext(ScrubContext);
  if (!scrub || points.length === 0) return null;
  const point = points[Math.min(scrub.index, points.length - 1)];
  const gap = point.y === null;
  const at = { left: `${point.x}%`, top: `${point.y ?? 0}%` };
  return (
    <div className={gap ? "scrub-cursor is-gap" : "scrub-cursor"} aria-hidden>
      {!gap && (
        <span className="scrub-glow">
          <span className="scrub-glow-box">
            <span className="scrub-lamp" style={at} />
          </span>
        </span>
      )}
      <span className="scrub-stem" style={at} />
      {!gap && <span className="scrub-dot" style={at} />}
    </div>
  );
}
