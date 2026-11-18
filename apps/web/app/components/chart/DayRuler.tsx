"use client";

// The day ruler: one client piece that reads a per-day chart. The chart stays
// server-rendered (BaselineRibbon does the math and hands ScrubCursor its
// point positions); this file only holds which day is selected and whether a
// drag is in progress.
//
//   <DayScrub series={...}>        selected day + drag state; marks the scope
//     ...chart with <ScrubCursor>  stem, dot and glow on the selected day, and
//                                  a layer that drives the handle from the chart
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
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";
import {
  nearestDay,
  scrubAnswer,
  scrubValueText,
  startPress,
  takesHandle,
  type ScrubPress,
  type ScrubSeries,
} from "./dayScrub";

type Scrub = {
  series: ScrubSeries;
  index: number;
  dragging: boolean;
  select: (index: number) => void;
  setDragging: (dragging: boolean) => void;
  ruler: RefObject<HTMLDivElement | null>;
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
  const ruler = useRef<HTMLDivElement>(null);
  const select = useCallback(
    (next: number) => setIndex(Math.min(last, Math.max(0, Math.round(next)))),
    [last],
  );
  return (
    <ScrubContext.Provider
      value={{ series, index: Math.min(index, last), dragging, select, setDragging, ruler }}
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

// Pointer handling for anything that drives the handle: the ruler, and the
// chart above it. `xs` are the days' positions as fractions of the element's
// width. A mouse or pen press takes the handle at once; a finger waits until
// it has clearly moved sideways (takesHandle), so a vertical swipe still
// scrolls the page and leaves the selected day alone; a tap selects.
function useScrubPointer(xs: number[]) {
  const scrub = useContext(ScrubContext);
  const press = useRef<ScrubPress | null>(null);
  const at = (event: PointerEvent<HTMLElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return nearestDay(xs, box.width > 0 ? (event.clientX - box.left) / box.width : 0);
  };
  const end = () => {
    const was = press.current?.active;
    press.current = null;
    if (was) scrub?.setDragging(false);
  };
  return {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      if (!scrub || event.button !== 0) return;
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Synthetic or already-released pointers cannot be captured; dragging
        // still works while the pointer stays over the element.
      }
      press.current = startPress(event.pointerType, event.clientX, event.clientY);
      if (!press.current.active) return;
      scrub.setDragging(true);
      scrub.select(at(event));
    },
    onPointerMove: (event: PointerEvent<HTMLElement>) => {
      const held = press.current;
      if (!scrub || !held) return;
      if (!held.active) {
        if (!takesHandle(held, event.clientX, event.clientY)) return;
        held.active = true;
        scrub.setDragging(true);
      }
      scrub.select(at(event));
    },
    onPointerUp: (event: PointerEvent<HTMLElement>) => {
      if (scrub && press.current && !press.current.active) scrub.select(at(event)); // a tap
      end();
    },
    onPointerCancel: end,
    onLostPointerCapture: end,
  };
}

export function DayRuler({ label }: { label: string }) {
  const scrub = useContext(ScrubContext);
  const count = scrub?.series.days.length ?? 0;
  const pointer = useScrubPointer(Array.from({ length: count }, (_, i) => frac(i, count)));
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = scrub?.ruler.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [scrub?.ruler]);

  if (!scrub || count === 0) return null;
  const { series, index, dragging, select } = scrub;
  const days = series.days;
  const day = days[index];
  const big = 7;

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
        ref={scrub.ruler}
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
        {...pointer}
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

// Every day's answer also sits, unseen, in the same grid cell as the one shown,
// so the line keeps the height of its longest answer. A gap day reads shorter
// and a note longer; moving the ruler never moves what is under the line.
export function ScrubAnswer({ className }: { className?: string }) {
  const scrub = useContext(ScrubContext);
  const series = scrub?.series;
  const sizes = useMemo(
    () => (series ? series.days.map((day) => scrubAnswer(day, series)) : []),
    [series],
  );
  if (!scrub || scrub.series.days.length === 0) return null;
  const answer = scrubAnswer(scrub.series.days[scrub.index], scrub.series);
  const name = className ? `scrub-answer ${className}` : "scrub-answer";
  return (
    <div className="scrub-answer-slot">
      <p className={name}>
        <b>{answer.value}</b>
        {answer.rest}
      </p>
      {sizes.map((size, i) => (
        <p key={i} className={`${name} scrub-answer-size`} aria-hidden>
          <b>{size.value}</b>
          {size.rest}
        </p>
      ))}
    </div>
  );
}

// Positions are percentages of the plot box, computed by the chart.
export type ScrubPoint = { x: number; y: number | null };

export function ScrubCursor({ points }: { points: ScrubPoint[] }) {
  const scrub = useContext(ScrubContext);
  const pointer = useScrubPointer(points.map((point) => point.x / 100));
  if (!scrub || points.length === 0) return null;
  const point = points[Math.min(scrub.index, points.length - 1)];
  const gap = point.y === null;
  const at = { left: `${point.x}%`, top: `${point.y ?? 0}%` };
  // Pressing the chart works the ruler: on release the slider takes focus, as
  // a native slider does when its track is clicked, so the arrow keys carry
  // on from the picked day. Focus moves after the press has settled, so a
  // mouse user gets no focus ring. A finger gets no focus (no keyboard).
  const onPointerUp = (event: PointerEvent<HTMLElement>) => {
    pointer.onPointerUp(event);
    if (event.button === 0 && event.pointerType !== "touch") {
      scrub.ruler.current?.focus({ preventScroll: true });
    }
  };
  return (
    <div className={gap ? "scrub-cursor is-gap" : "scrub-cursor"} aria-hidden>
      <div className="scrub-surface" {...pointer} onPointerUp={onPointerUp} />
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
