"use client";

import Link from "next/link";
import { useState } from "react";
import { formatValue } from "../lib/format";
import {
  readingDate,
  trendWindow,
  type TodayTrendOption,
} from "../lib/todayPresentation";
import { BaselineRibbon } from "./BaselineRibbon";
import { DayRuler, DayScrub, ScrubAnswer } from "./chart/DayRuler";
import { buildScrubSeries, calendarDays, usualBand } from "./chart/dayScrub";
import { useTodayExploration } from "./TodayExploration";

export function TodayTrend({
  options,
  now,
}: {
  options: TodayTrendOption[];
  now: string;
}) {
  const exploration = useTodayExploration();
  const [tableOpen, setTableOpen] = useState(false);
  const range = exploration?.range ?? 30;
  const option =
    options.find((item) => item.id === exploration?.selectedId) ?? options[0];
  if (!option) return null;
  const days = trendWindow(option.days, range, now);
  const dailyTotal = option.kind === "daily-total";
  const sleepMinutes = option.id === "sleep.duration" && option.unit === "min";
  const displayValue = (value: number) =>
    sleepMinutes
      ? `${Math.floor(Math.round(value) / 60)}h ${Math.round(value) % 60}m`
      : formatValue(value, option.unit);
  // The same number without its unit, for the handle and the lens.
  const bareValue = (value: number) =>
    sleepMinutes ? displayValue(value) : formatValue(value);
  const description = dailyTotal
    ? "Daily totals"
    : option.kind === "nightly"
      ? "Time asleep per night"
      : "Daily medians";
  const href =
    option.id === "sleep.duration"
      ? "/sleep"
      : `/library/${encodeURIComponent(option.id)}?range=${range}d`;
  const series =
    days.length >= 2
      ? buildScrubSeries({
          dates: calendarDays(now, range),
          readings: days,
          band: usualBand(days.map((day) => day.value)),
          unit: sleepMinutes ? "" : option.unit,
          format: bareValue,
          incompleteLatest: dailyTotal,
        })
      : null;
  const lastReading = option.latestAt ? readingDate(option.latestAt) : null;
  const tableId = "today-trend-values";

  const card = (
    <>
      <div className="today-trend-field">
        <header className="today-trend-head scrub-soft">
          <div className="today-trend-top">
            <span className="today-eyebrow">Explore a reading</span>
            <div className="today-range" role="group" aria-label="Chart time range">
              {([7, 30] as const).map((count) => (
                <button
                  key={count}
                  type="button"
                  aria-pressed={range === count}
                  onClick={() => exploration?.setRange(count)}
                >
                  {count} days
                </button>
              ))}
            </div>
          </div>
          <h2>
            <label className="today-trend-pick">
              <span id="today-trend-title">{option.title}</span>
              <svg viewBox="0 0 12 12" aria-hidden>
                <path d="M2.5 4.5 6 8l3.5-3.5" />
              </svg>
              <select
                aria-label="Reading"
                value={option.id}
                onChange={(event) => exploration?.select(event.target.value)}
              >
                {options.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
          </h2>
          <p className="today-trend-help" aria-live="polite" aria-atomic="true">
            {description} · {days.length} of {range} days recorded
          </p>
        </header>
        {series ? (
          <div className="today-trend-chart">
            <BaselineRibbon
              values={[]}
              scrub={series}
              height={150}
              ariaLabel={`${option.title}: ${description.toLowerCase()} over ${range} days, with your usual range as a band`}
            />
          </div>
        ) : (
          <div className="today-trend-empty">
            <strong>
              {days.length === 1
                ? "One day recorded in this window"
                : "No readings in this window"}
            </strong>
            <p>
              {range === 7 && option.days.length > days.length
                ? "Choose 30 days to see earlier readings."
                : "A trend will appear after at least two recorded days."}
              {lastReading ? ` Last reading ${lastReading}.` : ""}
            </p>
            <Link href="/sources">
              Check your sources <span aria-hidden>→</span>
            </Link>
          </div>
        )}
      </div>
      <div className="today-trend-body">
        {series && (
          <>
            <DayRuler label={`${option.title}, day`} />
            <ScrubAnswer />
          </>
        )}
        <div className="today-trend-meta scrub-soft">
          <span>{option.source} · dates in UTC</span>
          <span className="today-trend-links">
            <Link href={href}>
              Full history <span aria-hidden>↗</span>
            </Link>
            <Link href="/compare">
              Compare <span aria-hidden>↗</span>
            </Link>
            {days.length > 0 && (
              <button
                type="button"
                aria-expanded={tableOpen}
                aria-controls={tableId}
                onClick={() => setTableOpen((open) => !open)}
              >
                Daily values <span aria-hidden>{tableOpen ? "▴" : "▾"}</span>
              </button>
            )}
          </span>
        </div>
        {days.length > 0 && (
          <div
            className="today-trend-table-wrap scrub-soft"
            id={tableId}
            hidden={!tableOpen}
            tabIndex={0}
            role="region"
            aria-label={`${option.title} daily values`}
          >
            <table>
              <caption>
                {option.title} · {description.toLowerCase()} · UTC.
                {series?.usual
                  ? ` Your usual range, ${series.usual[0]} to ${series.usual[1]}${
                      series.unit ? ` ${series.unit}` : ""
                    }, is the middle half of these days.`
                  : ""}
                {dailyTotal ? " The latest day may be incomplete." : ""}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">
                    {dailyTotal
                      ? "Total"
                      : option.kind === "nightly"
                        ? "Time asleep"
                        : "Median"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...days].reverse().map((day) => (
                  <tr key={day.date}>
                    <th scope="row">
                      <time dateTime={day.date}>{readingDate(day.date)}</time>
                    </th>
                    <td>{displayValue(day.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );

  return (
    <article
      className="card today-trend"
      id="today-reading-detail"
      aria-labelledby="today-trend-title"
      tabIndex={-1}
      ref={exploration?.registerDetail}
    >
      {series ? (
        <DayScrub key={`${option.id}-${range}`} series={series}>
          {card}
        </DayScrub>
      ) : (
        card
      )}
    </article>
  );
}
