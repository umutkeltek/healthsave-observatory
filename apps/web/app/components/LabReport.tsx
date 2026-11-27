"use client";

import { useEffect, useState } from "react";
import type { LabImportReport } from "../lib/labImportTypes";
import { reportSpecimenDate } from "../lib/labReview";
import { DeleteLabDocument } from "./DeleteLabDocument";

export function LabReport({ documentId }: { documentId: string }) {
  const [report, setReport] = useState<LabImportReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    fetch(`/api/lab-imports/${encodeURIComponent(documentId)}/report`, { cache: "no-store", signal: abort.signal })
      .then(async response => { const body = await response.json(); if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The report could not be loaded."); return body as LabImportReport; })
      .then(setReport).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [documentId]);

  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "healthsave-lab-report.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (error) return <div className="card" role="alert"><p>{error}</p><a href="/labs/import">Back to documents</a></div>;
  if (!report) return <p className="card" role="status">Opening your report…</p>;
  return <article className="lab-report">
    <header className="prov-intro labs-intro"><a href="/labs">← Blood tests</a><h2>Your reviewed lab record</h2><p>{report.file_name} · {report.results.length} result{report.results.length === 1 ? "" : "s"}</p>
      <div className="lab-import-actions lab-no-print"><a className="btn btn-ghost" href={`/api/lab-imports/${report.id}/original`}>Download original</a><button className="btn btn-ghost" onClick={download}>Download JSON</button><button className="btn" onClick={() => window.print()}>Print / Save PDF</button><a href="/labs/import">Import another report</a></div>
    </header>
    <section className="card"><h3>What this report can tell you</h3><p>{report.review_status}</p><ul>{report.limitations.map(line => <li key={line}>{line}</li>)}</ul></section>
    {report.results.map((result, index) => <section className="card lab-report-result" key={`${result.loinc}-${index}`}>
      <div className="lab-import-heading"><h3>{result.marker}</h3><strong className="mono">{result.comparator ?? ""}{result.value} {result.unit}</strong></div>
      <p>{result.lab} · {reportSpecimenDate(result.specimen_at, result.quality_flags)} · Lab range: {result.reference_low ?? "—"} to {result.reference_high ?? "—"} {result.unit}</p>
      <p className="lab-report-observation">{result.observation}</p>
      <dl className="lab-report-evidence"><dt>Measurement quality</dt><dd>{result.measurement_quality}</dd><dt>Personal pattern</dt><dd>{result.personal_pattern}</dd><dt>Medical evidence</dt><dd>{result.medical_evidence}</dd></dl>
      {result.source_excerpt ? <blockquote><p>{result.source_excerpt}</p><footer>Original source{result.source_page ? ` · page ${result.source_page}` : ""}</footer></blockquote> : <p>Entered manually; no source excerpt was attached.</p>}
      <p className="lab-no-print"><a href={`/labs?marker=${encodeURIComponent(result.loinc)}`}>Compare this marker with your history →</a></p>
    </section>)}
    <section className="card"><h3>Scientific sources and scope</h3>{report.sources.map(source => <div key={source.id}><p><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></p><p>{source.scope}</p><p>Source checked {source.accessed_on}. This does not constitute clinical validation.</p></div>)}
      <details><summary>Record provenance</summary><p>Imported {report.imported_at} · Report version {report.report_version}</p><p className="lab-report-hash">Original SHA-256: {report.sha256}</p></details>
    </section>
    <DeleteLabDocument documentId={report.id} />
  </article>;
}
