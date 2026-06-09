import type { Divergence } from "../lib/provenance";

// The signature honesty primitive: when sources disagree, every reading is kept
// verbatim — never merged into a synthetic consensus.
//
// `live` (a reachable backend with real streams) renders the principle rather
// than fixture disagreements, because divergence detection is not wired to an
// API yet and fabricating disagreements would be the exact dishonesty this
// section exists to refuse. The demo path renders the illustrative cards.
export function DivergenceLog({ divergences, live }: { divergences: Divergence[]; live?: boolean }) {
  if (live) {
    return (
      <article className="card div-empty">
        <p className="empty">
          When two sources disagree, both readings are kept — never averaged into a synthetic consensus.
          We narrate from the higher-confidence source (more direct modality → more validated device →
          more consistent stream), because the gap is the signal, not a blended number. Flagged
          divergences surface here in a later release.
        </p>
      </article>
    );
  }

  return (
    <div className="div-stack">
      {divergences.map((d) => (
        <article className={`card div-card ${d.warn ? "div-warn" : ""}`} key={d.metric}>
          <div className="div-head">
            <span className="div-metric">
              {d.metric}
              {d.context ? <span className="div-ctx"> ({d.context})</span> : null}
            </span>
            {d.resolution ? (
              <span className="badge both-kept">{d.resolution}</span>
            ) : d.warn ? (
              <span className="div-flag" aria-hidden>
                ⚠
              </span>
            ) : null}
          </div>
          {d.readings.length > 0 && (
            <div className="div-readings">
              <span className="div-dot" aria-hidden />
              {d.readings.map((r, i) => (
                <span className="div-reading" key={r.source}>
                  {i > 0 && (
                    <span className="div-sep" aria-hidden>
                      ›
                    </span>
                  )}
                  <span className="div-rsrc">{r.source}:</span> <span className="div-rval">{r.value}</span>
                </span>
              ))}
            </div>
          )}
          {d.note && <p className="div-note">{d.note}</p>}
          {d.stance && <p className="div-stance">{d.stance}</p>}
        </article>
      ))}
    </div>
  );
}
