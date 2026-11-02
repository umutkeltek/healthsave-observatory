import type { Metadata } from "next";

import { FindingCardView } from "../components/FindingCard";
import { LabChart } from "../components/LabChart";
import type { LabMarker, LabMarkerDetail, LabSource } from "../lib/api";
import {
  BAND_LABEL,
  BAND_SHORT,
  bandTone,
  changeSentence,
  gapSentence,
  historySentence,
  labDate,
  labRange,
  labSeriesIndex,
  labValue,
  latestResult,
  streakSentence,
} from "../lib/labs";
import { safeLabMarker, safeLabs } from "../lib/load";

export const metadata: Metadata = { title: "Labs · HealthSave Observatory" };
export const revalidate = 30;

type SearchParams = { marker?: string | string[] };

function LabLegend({ labs, streamOrder }: { labs: LabSource[]; streamOrder: string[] }) {
  return (
    <ul className="labs-legend" aria-label="Labs">
      {labs.map((lab) => (
        <li key={lab.stream_id} className="labs-legend-item">
          <span className={`labs-swatch labs-s${labSeriesIndex(streamOrder, lab.stream_id)}`} aria-hidden />
          <span>{lab.lab}</span>
          <span className="labs-legend-count mono">
            {lab.result_count} result{lab.result_count === 1 ? "" : "s"}
          </span>
        </li>
      ))}
    </ul>
  );
}

function MarkerRow({
  marker,
  selected,
  streamOrder,
}: {
  marker: LabMarker;
  selected: boolean;
  streamOrder: string[];
}) {
  const latest = latestResult(marker);
  if (!latest) return null;
  return (
    <li>
      <a
        className={`labs-row${selected ? " is-selected" : ""}`}
        href={`/labs?marker=${encodeURIComponent(marker.loinc)}`}
        aria-current={selected ? "true" : undefined}
      >
        <span className="labs-row-name">
          <span className="labs-row-title">{marker.name}</span>
          <span className="labs-row-sub">
            {latest.lab} · {labDate(latest.specimen_at)}
          </span>
        </span>
        <span className="labs-row-value mono">{labValue(latest)}</span>
        <span className={`labs-verdict labs-verdict-${bandTone(latest.band)}`}>{BAND_SHORT[latest.band]}</span>
        <span className="labs-row-spark">
          <LabChart
            results={marker.results}
            streamOrder={streamOrder}
            height={34}
            compact
            ariaLabel={`${marker.name}: ${marker.result_count} result${marker.result_count === 1 ? "" : "s"} against each lab's range`}
          />
        </span>
      </a>
    </li>
  );
}

function MarkerDetail({
  detail,
  labs,
  streamOrder,
}: {
  detail: LabMarkerDetail;
  labs: LabSource[];
  streamOrder: string[];
}) {
  const latest = latestResult(detail);
  if (!latest) return null;
  const assessment = detail.assessment;
  const notes = assessment
    ? [
        changeSentence(assessment, detail.display_unit),
        historySentence(assessment, detail.display_unit),
        streakSentence(assessment),
      ].filter((line): line is string => Boolean(line))
    : [];
  const markerLabs = labs.filter((lab) => detail.results.some((r) => r.stream_id === lab.stream_id));
  const match = detail.cross_match;

  return (
    <section className="labs-detail" aria-labelledby="labs-detail-title">
      <article className="card labs-detail-card">
        <header className="labs-detail-head">
          <div>
            <h3 id="labs-detail-title" className="labs-detail-title">
              {detail.name}
            </h3>
            <p className="labs-detail-latest">
              <span className="labs-detail-value mono">{labValue(latest)}</span>
              <span className={`labs-verdict labs-verdict-${bandTone(latest.band)}`}>{BAND_LABEL[latest.band]}</span>
            </p>
            <p className="labs-detail-meta">
              {latest.lab} · {labDate(latest.specimen_at)} · lab range {labRange(latest)}
            </p>
          </div>
        </header>

        {notes.length > 0 && (
          <ul className="labs-notes">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}

        <LabChart
          results={detail.results}
          streamOrder={streamOrder}
          ariaLabel={`${detail.name} over time, each result against its own lab's range`}
        />
        <LabLegend labs={markerLabs} streamOrder={streamOrder} />

        {detail.gaps.length > 0 && (
          <div className="labs-gaps">
            <h4 className="labs-subhead">Two labs, close together</h4>
            <p className="labs-gaps-intro">
              Each value is read against its own lab&apos;s range. They are shown side by side, not averaged.
            </p>
            <ul className="labs-gap-list">
              {detail.gaps.map((gap) => (
                <li key={`${gap.earlier_id}-${gap.later_id}`} className="labs-gap">
                  <div className="labs-gap-pair">
                    <span>
                      <span className="labs-gap-lab">{gap.earlier_lab}</span>{" "}
                      <span className="mono">
                        {labValue({ value: gap.earlier_value, comparator: null, display_unit: detail.display_unit })}
                      </span>{" "}
                      <span className={`labs-verdict labs-verdict-${bandTone(gap.earlier_band)}`}>
                        {BAND_SHORT[gap.earlier_band]}
                      </span>
                    </span>
                    <span>
                      <span className="labs-gap-lab">{gap.later_lab}</span>{" "}
                      <span className="mono">
                        {labValue({ value: gap.later_value, comparator: null, display_unit: detail.display_unit })}
                      </span>{" "}
                      <span className={`labs-verdict labs-verdict-${bandTone(gap.later_band)}`}>
                        {BAND_SHORT[gap.later_band]}
                      </span>
                    </span>
                  </div>
                  <p className="labs-gap-note">{gapSentence(gap, detail.display_unit)}</p>
                </li>
              ))}
            </ul>
          </div>
        )}

        <details className="labs-table-drill">
          <summary>All {detail.result_count} results</summary>
          <table className="labs-table">
            <thead>
              <tr>
                <th scope="col">Sample taken</th>
                <th scope="col">Value</th>
                <th scope="col">Lab range</th>
                <th scope="col">Lab</th>
                <th scope="col">Against its range</th>
              </tr>
            </thead>
            <tbody>
              {[...detail.results].reverse().map((result) => (
                <tr key={result.id}>
                  <td className="mono">{labDate(result.specimen_at)}</td>
                  <td className="mono">{labValue(result)}</td>
                  <td className="mono">{labRange(result)}</td>
                  <td>{result.lab}</td>
                  <td>{BAND_SHORT[result.band]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="labs-code mono">
            LOINC {detail.loinc} · stored as {detail.metric_id}
          </p>
        </details>
      </article>

      {match && (
        <div className="labs-cross">
          <h4 className="labs-subhead">
            {detail.name} and your {match.related_label}
          </h4>
          {match.card ? (
            <FindingCardView
              card={match.card}
              title={`Read together, ${match.stream_label ?? "one wearable source"}`}
              figure={
                <LabChart
                  results={detail.results}
                  streamOrder={streamOrder}
                  height={64}
                  compact
                  ariaLabel={`${detail.name} draws compared with your ${match.related_label}`}
                />
              }
            />
          ) : (
            <p className="card labs-cross-empty">{match.reason}</p>
          )}
        </div>
      )}
    </section>
  );
}

export default async function LabsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const requested = Array.isArray(sp.marker) ? sp.marker[0] : sp.marker;
  const overview = await safeLabs();

  const intro = (
    <div className="prov-intro labs-intro">
      <h2>Blood tests</h2>
      <p>
        Each marker against the range your lab printed and against your own earlier results. Results from
        different labs stay separate and are never averaged. This is a record, not a diagnosis.
      </p>
    </div>
  );

  if (!overview) {
    return (
      <>
        {intro}
        <p className="card labs-empty">The Observatory API did not answer, so lab results cannot be shown right now.</p>
      </>
    );
  }

  if (overview.markers.length === 0) {
    return (
      <>
        {intro}
        <div className="card labs-empty">
          <h3>No lab results yet</h3>
          <p>
            Import a CSV export of your results with <code>healthsave labs import results.csv</code>. The
            columns are described in <code>docs/capture/labs-csv.md</code>; the file stays on this machine.
          </p>
        </div>
      </>
    );
  }

  const streamOrder = overview.labs.map((lab) => lab.stream_id);
  const selected =
    overview.markers.find((marker) => marker.loinc === requested) ?? overview.markers[0];
  const detail = await safeLabMarker(selected.loinc);

  return (
    <>
      {intro}
      <div className="labs-layout">
        <section className="labs-index" aria-label="Markers">
          <div className="labs-index-head">
            <span>
              {overview.count} marker{overview.count === 1 ? "" : "s"} · {overview.result_count} results
            </span>
            <LabLegend labs={overview.labs} streamOrder={streamOrder} />
          </div>
          <ul className="labs-list">
            {overview.markers.map((marker) => (
              <MarkerRow
                key={marker.loinc}
                marker={marker}
                selected={marker.loinc === selected.loinc}
                streamOrder={streamOrder}
              />
            ))}
          </ul>
        </section>
        {detail ? (
          <MarkerDetail detail={detail} labs={overview.labs} streamOrder={streamOrder} />
        ) : (
          <p className="card labs-empty">This marker could not be loaded right now.</p>
        )}
      </div>
    </>
  );
}
