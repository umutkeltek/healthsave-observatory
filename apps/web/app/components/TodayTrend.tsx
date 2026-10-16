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
import { useTodayExploration } from "./TodayExploration";

export function TodayTrend({
  options,
  now,
}: {
  options: TodayTrendOption[];
  now: string;
}) {
  const exploration = useTodayExploration();
  const [range, setRange] = useState(30);
  const option =
    options.find((item) => item.id === exploration?.selectedId) ?? options[0];
  if (!option) return null;
  const days = trendWindow(option.days, range, now);
  const latest = days.at(-1);
  const dailyTotal = option.kind === "daily-total";
  const sleepMinutes = option.id === "sleep.duration" && option.unit === "min";
  const displayValue = (value: number) =>
    sleepMinutes
      ? `${Math.floor(Math.round(value) / 60)}h ${Math.round(value) % 60}m`
      : formatValue(value, option.unit);
  const description = dailyTotal
    ? "Daily totals"
    : option.kind === "nightly"
      ? "Time asleep per night"
      : "Daily medians";
  const href =
    option.id === "sleep.duration"
      ? "/sleep"
      : `/library/${encodeURIComponent(option.id)}?range=${range}d`;

  return (
    <article
      className="card today-trend"
      id="today-reading-detail"
      aria-label="Reading explorer"
    >
      <div className="today-section-heading">
        <div>
          <span className="today-eyebrow">Explore a reading</span>
          <h2 id="today-trend-title">{option.title} over time</h2>
        </div>
        <div className="today-range" role="group" aria-label="Chart time range">
          {[7, 30].map((count) => (
            <button
              key={count}
              type="button"
              aria-pressed={range === count}
              onClick={() => setRange(count)}
            >
              {count} days
            </button>
          ))}
        </div>
      </div>
      <div className="today-trend-controls">
        <label className="today-metric-picker">
          <span>Reading</span>
          <select
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
        <Link href={href}>
          Full history <span aria-hidden>↗</span>
        </Link>
      </div>
      <div
        className="today-trend-summary"
        aria-live="polite"
        aria-atomic="true"
      >
        <span>
          {description} · {days.length} of {range} days recorded
        </span>
        {latest && (
          <span>
            <strong>{displayValue(latest.value)}</strong> on{" "}
            {readingDate(latest.date)}
          </span>
        )}
      </div>
      {days.length >= 2 ? (
        <BaselineRibbon
          key={`${option.id}-${range}`}
          values={days.map((day) =>
            sleepMinutes ? day.value / 60 : day.value,
          )}
          timestamps={days.map((day) => day.date)}
          height={164}
          unit={sleepMinutes ? "h" : option.unit}
          axis={[
            readingDate(days[0].date),
            readingDate(days[days.length - 1].date),
          ]}
          hoverLabels={days.map((day) => readingDate(day.date))}
          ariaLabel={`${option.title}: ${description.toLowerCase()} over ${range} days`}
        />
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
          </p>
          <Link href="/sources">
            Check your sources <span aria-hidden>→</span>
          </Link>
        </div>
      )}
      <div className="today-trend-context">
        <span>{option.source}</span>
        <span>
          Dates in UTC
          {option.latestAt
            ? ` · Last reading ${readingDate(option.latestAt)}`
            : ""}
        </span>
      </div>
      <div className="today-trend-note">
        {days.length >= 2 && (
          <span>
            Band: middle 50% of shown days.
            {dailyTotal
              ? " Latest day may be incomplete."
              : " Gaps mean no readings."}
          </span>
        )}
        <Link href="/compare">
          Compare signals <span aria-hidden>↗</span>
        </Link>
      </div>
      {days.length > 0 && (
        <details
          className="today-trend-data"
          key={`${option.id}-${range}-data`}
        >
          <summary>View {days.length} daily values</summary>
          <div
            className="today-trend-table-wrap"
            tabIndex={0}
            role="region"
            aria-label={`${option.title} daily values`}
          >
            <table>
              <caption>
                {option.title} · {description.toLowerCase()} · UTC
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
        </details>
      )}
    </article>
  );
}
