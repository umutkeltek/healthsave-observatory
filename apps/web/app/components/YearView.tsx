// Year in Health page body: pure (props in, markup out) so it renders in tests
// without a backend. Everything shown comes from the API; this only lays it
// out. Gaps are drawn day by day and listed in full; nothing is averaged.

import type { YearFamily, YearHeadline, YearInHealth, YearMonth, YearSource } from "../lib/api";
import {
  CONFIDENCE_LABEL,
  changeSentence,
  dateRange,
  gapSentence,
  gapSummary,
  headlineRange,
  headlineValue,
  insideGaps,
  isAllSourcesTotal,
  isPerSource,
  limitationSentence,
  maskRuns,
  MONTH_NAMES,
  MONTH_SHORT,
  monthCalendar,
  monthCoverage,
  neighbourYears,
  plural,
  shortDate,
  sourceSlot,
  withheldSentence,
} from "../lib/year";
import { type CardOptions, cardLabel, cardQuery } from "../lib/yearCard";
import { YearCardDownload } from "./YearCardDownload";
import { YearCardOptionsForm } from "./YearCardOptionsForm";

function Confidence({ value }: { value: YearMonth["confidence"] }) {
  const label = CONFIDENCE_LABEL[value];
  if (!label) return null;
  return <span className={`yr-chip yr-chip-${value}`}>{label}</span>;
}

function MonthTile({
  summary,
  month,
  order,
}: {
  summary: YearInHealth;
  month: YearMonth;
  order: string[];
}) {
  const weeks = monthCalendar(summary, month.month);
  const byId = new Map(summary.sources.map((s) => [s.stream_id, s]));
  const name = MONTH_NAMES[month.month - 1];
  return (
    <li className={`yr-month yr-month-${month.confidence}`}>
      <div className="yr-month-head">
        <span className="yr-month-name">{MONTH_SHORT[month.month - 1]}</span>
        <span className="yr-month-count mono" title={`${name}: days with any data`}>
          {monthCoverage(month)}
        </span>
      </div>
      <div className="yr-cal" role="img" aria-label={`${name}: ${month.days_with_data} of ${month.days} days with data`}>
        {weeks.flat().map((cell, i) => {
          if (cell.kind === "blank") return <span key={i} className="yr-cell is-blank" />;
          if (cell.kind === "future") return <span key={i} className="yr-cell is-future" />;
          return (
            <span
              key={i}
              className={`yr-cell ${cell.level === 0 ? "is-gap" : `yr-l${cell.level}`}`}
              data-day={cell.iso}
              title={`${shortDate(cell.iso)}: ${cell.families === 0 ? "nothing recorded" : plural(cell.families, "kind") + " of data"}`}
            />
          );
        })}
      </div>
      {month.source_ids.length > 0 && (
        <div className="yr-month-sources" aria-label="Sources this month">
          {month.source_ids.map((id) => (
            <span
              key={id}
              className={`yr-swatch yr-s${sourceSlot(order, id)}`}
              title={byId.get(id)?.label ?? "source"}
            />
          ))}
        </div>
      )}
      {(month.first_seen_ids.length > 0 || month.last_seen_ids.length > 0) && (
        <ul className="yr-month-changes">
          {month.first_seen_ids.map((id) => (
            <li key={`f-${id}`} className="yr-change-new" title={`New: ${byId.get(id)?.label ?? "a source"}`}>
              New: {byId.get(id)?.label ?? "a source"}
            </li>
          ))}
          {month.last_seen_ids.map((id) => (
            <li key={`l-${id}`} className="yr-change-stop" title={`Last reading: ${byId.get(id)?.label ?? "a source"}`}>
              Last: {byId.get(id)?.label ?? "a source"}
            </li>
          ))}
        </ul>
      )}
      <Confidence value={month.confidence} />
    </li>
  );
}

function FamilyRow({ family, days }: { family: YearFamily; days: number }) {
  const inside = insideGaps(family.gaps);
  return (
    <li className="yr-family">
      <div className="yr-family-head">
        <span className="yr-family-name">{family.label}</span>
        <span className="yr-family-count mono">
          {family.days_with_data} of {days} days
        </span>
        <Confidence value={family.confidence} />
      </div>
      <svg
        className="yr-family-strip"
        viewBox={`0 0 ${days} 10`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${family.label}: ${family.days_with_data} days with data, ${family.days_without_data} without`}
      >
        {maskRuns(family.mask).map(([start, length, ch]) => (
          <rect
            key={start}
            className={ch === "1" ? "yr-run" : "yr-run-gap"}
            x={start}
            y={0}
            width={length}
            height={10}
          />
        ))}
      </svg>
      <p className="yr-family-gaps">{gapSummary(family.gaps)}</p>
      {family.gaps.length > 0 && (
        <details className="yr-drill">
          <summary>
            Every day without {family.label.toLowerCase()} data ({plural(family.days_without_data, "day")}
            {inside.length > 0 ? `, ${plural(inside.length, "gap")} inside the record` : ""})
          </summary>
          <ul className="yr-gap-list">
            {family.gaps.map((gap) => (
              <li key={gap.start} className={`yr-gap yr-gap-${gap.kind}`} data-gap-days={gap.days}>
                {gapSentence(gap)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function SourceRow({ source, order }: { source: YearSource; order: string[] }) {
  return (
    <li className="yr-source">
      <span className={`yr-swatch yr-s${sourceSlot(order, source.stream_id)}`} aria-hidden />
      <span className="yr-source-name">
        <span className="yr-source-title">{source.label}</span>
        <span className="yr-source-sub">
          {dateRange(source.first_day, source.last_day)} · {plural(source.days_with_data, "day")}
        </span>
      </span>
      <span className="yr-source-months" aria-label={`Months with readings from ${source.label}`}>
        {MONTH_SHORT.map((label, i) => (
          <span
            key={label}
            className={`yr-source-month${source.months.includes(i + 1) ? ` is-on yr-s${sourceSlot(order, source.stream_id)}` : ""}`}
            title={label}
          />
        ))}
      </span>
      <span className="yr-source-tags">
        {source.new_this_year && <span className="yr-chip yr-chip-new">New this year</span>}
        {source.stopped_this_year && <span className="yr-chip yr-chip-stop">Stopped</span>}
      </span>
    </li>
  );
}

function HeadlineItem({ headline }: { headline: YearHeadline }) {
  const range = headlineRange(headline);
  return (
    <li className="yr-headline">
      <span className="yr-headline-label">
        {headline.label}
        {isPerSource(headline) && headline.source_label ? <span className="yr-headline-source"> · {headline.source_label}</span> : null}
      </span>
      <span className="yr-headline-value mono">{headlineValue(headline)}</span>
      {(range || headline.days !== null) && (isPerSource(headline) || isAllSourcesTotal(headline)) && (
        <span className="yr-headline-sub">
          {range}
          {range && headline.days !== null ? " · " : ""}
          {headline.days !== null ? plural(headline.days, "day") : ""}
        </span>
      )}
      <Confidence value={headline.confidence} />
    </li>
  );
}

function Intro({ year }: { year: number }) {
  const { previous, next } = neighbourYears(year);
  return (
    <div className="prov-intro yr-intro">
      <div className="yr-intro-head">
        <h2>{year}, the year in your record</h2>
        <nav className="yr-years" aria-label="Other years">
          <a href={`/year/${previous}`}>← {previous}</a>
          {next !== null && <a href={`/year/${next}`}>{next} →</a>}
        </nav>
      </div>
      <p>
        Which days hold data, from which devices, and where the gaps are. Each source keeps its own numbers;
        nothing is averaged across devices. This is a record, not a diagnosis.
      </p>
    </div>
  );
}

export function YearView({
  year,
  summary,
  options,
  notStarted = false,
}: {
  year: number;
  summary: YearInHealth | null;
  options: CardOptions;
  notStarted?: boolean;
}) {
  if (notStarted) {
    return (
      <>
        <Intro year={year} />
        <p className="card yr-empty">
          {year} has not started yet in your time zone. The view follows the time zone and day start in
          Settings.
        </p>
      </>
    );
  }
  if (!summary) {
    return (
      <>
        <Intro year={year} />
        <p className="card yr-empty">
          The Observatory API did not answer, so this year cannot be shown right now. A large record can take a
          while the first time; reload in a minute.
        </p>
      </>
    );
  }

  const order = summary.sources.map((s) => s.stream_id);
  const days = summary.days_in_window;
  const empty = summary.days_with_data === 0;
  const recordHeadlines = summary.headlines.filter((h) => !isPerSource(h) && !isAllSourcesTotal(h));
  const sourceHeadlines = summary.headlines.filter(isPerSource);
  const totalHeadlines = summary.headlines.filter(isAllSourcesTotal);
  const allGaps = summary.gaps;
  const query = cardQuery(options);

  return (
    <>
      <Intro year={year} />

      <section className="yr-summary card" aria-label="The year at a glance">
        <ul className="yr-headlines yr-headlines-record">
          {recordHeadlines.map((h) => (
            <HeadlineItem key={h.id} headline={h} />
          ))}
        </ul>
        <p className="yr-window">
          {shortDate(summary.window_start)} – {shortDate(summary.window_end)}
          {summary.window_end < `${year}-12-31` ? " (so far)" : ""} · {summary.time_zone}, days start at{" "}
          {summary.day_boundary}
          {summary.confidence === "low" && (
            <span className="yr-chip yr-chip-low">Low confidence: data on fewer than half the days</span>
          )}
        </p>
      </section>

      {empty ? (
        <div className="card yr-empty">
          <h3>Nothing recorded in {year}</h3>
          <p>This Observatory holds no readings for {year}. Pick another year above, or sync the app.</p>
        </div>
      ) : (
        <>
          <section className="yr-section" aria-labelledby="yr-months-title">
            <h3 id="yr-months-title" className="yr-subhead">
              Month by month
            </h3>
            <ol className="yr-months">
              {summary.months.map((month) => (
                <MonthTile key={month.month} summary={summary} month={month} order={order} />
              ))}
            </ol>
            <p className="yr-legend">
              <span className="yr-cell yr-l4" aria-hidden /> more kinds of data
              <span className="yr-cell yr-l1" aria-hidden /> fewer
              <span className="yr-cell is-gap" aria-hidden /> nothing recorded
            </p>
          </section>

          <section className="yr-section" aria-labelledby="yr-families-title">
            <h3 id="yr-families-title" className="yr-subhead">
              What was recorded, day by day
            </h3>
            <p className="yr-section-note">{gapSummary(allGaps)} A gap is a day with no reading of any kind.</p>
            <ul className="yr-families">
              {summary.families.map((family) => (
                <FamilyRow key={family.id} family={family} days={days} />
              ))}
            </ul>
            {allGaps.length > 0 && (
              <details className="yr-drill">
                <summary>Every day with nothing at all ({plural(days - summary.days_with_data, "day")})</summary>
                <ul className="yr-gap-list">
                  {allGaps.map((gap) => (
                    <li key={gap.start} className={`yr-gap yr-gap-${gap.kind}`} data-gap-days={gap.days}>
                      {gapSentence(gap)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>

          <section className="yr-section" aria-labelledby="yr-sources-title">
            <h3 id="yr-sources-title" className="yr-subhead">
              Sources and device changes
            </h3>
            {summary.sources.length === 0 ? (
              <p className="yr-section-note">
                No device-level readings this year; only totals the phone adds up across sources.
              </p>
            ) : (
              <ul className="yr-sources">
                {summary.sources.map((source) => (
                  <SourceRow key={source.stream_id} source={source} order={order} />
                ))}
              </ul>
            )}
            {summary.device_changes.length > 0 && (
              <ul className="yr-changes">
                {summary.device_changes.map((change) => (
                  <li key={`${change.kind}-${change.stream_id}`} className={`yr-change yr-change-${change.kind}`}>
                    {changeSentence(change)}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {(sourceHeadlines.length > 0 || totalHeadlines.length > 0 || summary.withheld.length > 0) && (
            <section className="yr-section" aria-labelledby="yr-numbers-title">
              <h3 id="yr-numbers-title" className="yr-subhead">
                A few numbers, one source at a time
              </h3>
              <p className="yr-section-note">
                The middle value of the year&apos;s readings from each source, and the range most days fell in.
                Two devices are never blended into one number.
              </p>
              <ul className="yr-headlines">
                {sourceHeadlines.map((h) => (
                  <HeadlineItem key={`${h.id}-${h.stream_id ?? "all"}`} headline={h} />
                ))}
              </ul>
              {totalHeadlines.length > 0 && (
                <>
                  <p className="yr-section-note yr-totals-note">
                    The phone&apos;s own daily total, which it adds up across every source. It is one series as
                    the phone reports it, not a device.
                  </p>
                  <ul className="yr-headlines">
                    {totalHeadlines.map((h) => (
                      <HeadlineItem key={`${h.id}-total`} headline={h} />
                    ))}
                  </ul>
                </>
              )}
              {summary.withheld.length > 0 && (
                <ul className="yr-withheld">
                  {summary.withheld.map((item) => (
                    <li key={`${item.id}-${item.stream_id ?? "all"}`}>{withheldSentence(item)}</li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section className="yr-section yr-share" aria-labelledby="yr-share-title">
            <h3 id="yr-share-title" className="yr-subhead">
              Share card
            </h3>
            <div className="yr-share-layout">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                className="yr-card-preview"
                src={`/year/${year}/card${query}`}
                width={540}
                height={675}
                alt={cardLabel(summary, options)}
              />
              <div className="yr-share-controls">
                <p>
                  By default the card shows only the shape of your year: one line per day, a short grey mark where
                  nothing was recorded, and a dot where a device started or stopped. No counts, no dates, no device
                  names. Add them only if you want them on it.
                </p>
                <YearCardOptionsForm year={year} options={options} />
                <YearCardDownload year={year} query={query} />
              </div>
            </div>
          </section>
        </>
      )}

      <section className="yr-section yr-limits" aria-labelledby="yr-limits-title">
        <h3 id="yr-limits-title" className="yr-subhead">
          What this view cannot tell you
        </h3>
        <ul>
          {summary.limitations.map((item) => (
            <li key={item.code}>{limitationSentence(item, summary)}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
