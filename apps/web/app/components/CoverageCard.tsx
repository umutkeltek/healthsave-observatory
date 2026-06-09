import { coverageVerdict, reliabilityFor } from "../lib/healthOpinion";
import type { Coverage } from "../lib/provenance";

// Coverage — NOT "confidence". One bar per source; the headline is the mean of
// those bars (an average over your own data), never a synthesized judgement of
// which disagreeing source is correct. The card also takes a STANCE: a verdict
// on ingestion health and a grounded reliability tag per source.
export function CoverageCard({ headline, domains }: Coverage) {
  const verdict = coverageVerdict(domains);

  if (domains.length === 0) {
    return (
      <article className="card coverage">
        <div className="cov-top">
          <h2>Coverage</h2>
          <span className={`cov-state ${verdict.state}`}>{verdict.label}</span>
        </div>
        <p className="empty">{verdict.line}</p>
      </article>
    );
  }

  return (
    <article className="card coverage">
      <div className="cov-top">
        <h2>Coverage</h2>
        <span className={`cov-state ${verdict.state}`}>{verdict.label}</span>
      </div>
      <div className="cov-headline">
        <span className="cov-num">
          {headline}
          <span className="cov-pct">%</span>
        </span>
        <span className="cov-sub">mean device freshness</span>
      </div>
      <p className="cov-verdict">{verdict.line}</p>
      <ul className="cov-list">
        {domains.map((d) => {
          const rel = reliabilityFor(d.label);
          return (
            <li className="cov-row" key={d.id}>
              <span className="cov-label" title={rel.note}>
                <span className="cov-name">
                  <span
                    className={`cov-conf ${rel.confidence}`}
                    aria-label={`${rel.confidence} confidence`}
                  />
                  {d.label}
                </span>
                <span className="cov-rel">
                  {rel.tag} · {rel.best} · <span className="cov-conf-label">{rel.confidence}</span>
                </span>
              </span>
              <span className="cov-track">
                <span className={`cov-fill ${d.tone}`} style={{ width: `${d.pct}%` }} />
              </span>
              <span className="cov-val">{d.pct}%</span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
