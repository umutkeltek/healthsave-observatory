"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  GeneticDocument, GeneticDocumentDetail, GeneticIndex, GeneticReference,
  GeneticReferenceStatus, GeneticReport,
} from "../lib/geneticContracts.generated";

async function responseBody<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "This request could not be completed.");
  return body as T;
}
const get = <T,>(path: string, signal?: AbortSignal) => fetch(`/api/genetics${path}`, { cache: "no-store", signal }).then(responseBody<T>);
const action = <T,>(path: string, body: object, method = "POST") => fetch(`/api/genetics${path}`, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
}).then(responseBody<T>);
const ignoreReferences = (_references: GeneticReference[]) => {};

export function GeneticReferencePanel({ onReferences = ignoreReferences }: { onReferences?: (references: GeneticReference[]) => void }) {
  const [status, setStatus] = useState<GeneticReferenceStatus | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const running = status?.job.state === "downloading" || status?.job.state === "indexing";
  const load = useCallback(async () => {
    try {
      const value = await get<GeneticReferenceStatus>("/reference");
      setStatus(value); onReferences(value.references); setError("");
    } catch (e) { setError((e as Error).message); }
  }, [onReferences]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [running, load]);
  async function install(assembly: string) {
    setStarting(true); setError("");
    try {
      const value = await action<GeneticReferenceStatus>("/reference", { assembly, confirmed });
      setStatus(value); onReferences(value.references);
    } catch (e) { setError((e as Error).message); }
    finally { setStarting(false); }
  }
  return <section className="card genetic-reference lab-no-print">
    <h3>Public scientific reference</h3>
    <p>ClinVar annotations are matched on your Observatory. Reference downloads contain public data; your DNA is never included in the request.</p>
    {error && <p role="alert">{error}</p>}
    {!status && !error && <p role="status">Checking installed references…</p>}
    {status?.references.length === 0 && <p>Install the reference for your file’s genome build before importing.</p>}
    {status?.references.map(reference => <p key={reference.assembly}><strong>{reference.assembly}</strong> · release {reference.release_date} · {reference.record_count.toLocaleString()} supported annotations</p>)}
    {status && status.job.state !== "idle" && <p role="status" aria-live="polite">{status.job.message}
      {running && <> · {((status.job.bytes_downloaded ?? 0) / 1024 / 1024).toFixed(0)} MB downloaded · {(status.job.records_indexed ?? 0).toLocaleString()} indexed</>}
    </p>}
    <details open={status?.references.length === 0}>
      <summary>Install or update reference data</summary>
      <p>Each assembly requires a download of hundreds of MB and additional space for a local index. Updates can take several minutes. Completed reports keep their existing source version.</p>
      <label className="genetic-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={running || starting} />Download public ClinVar data from NCBI to this Observatory.</label>
      <div className="lab-import-actions">{["GRCh37", "GRCh38"].map(assembly => <button key={assembly} className="btn btn-ghost" disabled={!confirmed || running || starting} onClick={() => void install(assembly)}>
        {`${status?.references.some(r => r.assembly === assembly) ? "Update" : "Install"} ${assembly}`}
      </button>)}</div>
      <p><a href="https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/" target="_blank" rel="noreferrer">ClinVar data use and interpretation limits ↗</a></p>
    </details>
  </section>;
}

export function GeneticHome() {
  const router = useRouter();
  const [references, setReferences] = useState<GeneticReference[]>([]);
  const [documents, setDocuments] = useState<GeneticDocument[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [assembly, setAssembly] = useState("");
  const [forward, setForward] = useState(false);
  const [consent, setConsent] = useState(false);
  const [retain, setRetain] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const available = references.some(reference => reference.assembly === assembly);
  useEffect(() => {
    const abort = new AbortController();
    get<GeneticIndex>("", abort.signal).then(value => setDocuments(value.documents))
      .catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, []);
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !available || !forward || !consent || busy) return;
    if (file.size === 0 || file.size > 50 * 1024 * 1024 || !/\.(txt|tsv|vcf)(\.gz)?$/i.test(file.name)) {
      setError("Choose a non-empty TXT, TSV or VCF, optionally gzip-compressed, no larger than 50 MB."); return;
    }
    setBusy(true); setError("");
    try {
      const result = await fetch("/api/genetics", { method: "POST", body: file, headers: {
        "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name),
        "X-Genome-Assembly": assembly, "X-Forward-Strand": "confirmed", "X-Genetic-Consent": "accepted",
        "X-Retain-Original": String(retain),
      }}).then(responseBody<GeneticDocumentDetail>);
      router.push(`/genetics/${result.document.id}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="genetics">
    <section className="prov-intro"><h2>Explore the evidence in your DNA file</h2>
      <p>Connect your recorded variants with public ClinVar annotations. Each match shows its source review, conflicts, and limits. This is evidence retrieval, not a diagnosis or a personal risk score.</p>
      <a href="/labs">View your blood-test history →</a>
    </section>
    <GeneticReferencePanel onReferences={setReferences} />
    <form className="card genetic-upload" onSubmit={event => void upload(event)}>
      <h3>Import a genetic file</h3>
      <p>23andMe/Ancestry-style TXT or TSV, or a VCF with one sample. Gzip is supported; ZIP archives must be extracted first. Up to 50 MB compressed and 1,000,000 rows.</p>
      {error && <p role="alert">{error}</p>}
      <label>Genotype file<input type="file" accept=".txt,.tsv,.vcf,.gz" disabled={busy} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
      <label>Genome build as reported by your source<select value={assembly} disabled={busy} onChange={event => setAssembly(event.target.value)} required>
        <option value="">Choose the file’s build</option><option value="GRCh37">GRCh37 / hg19 / Build 37</option><option value="GRCh38">GRCh38 / Build 38</option>
      </select></label>
      {assembly && !available && <p>Install {assembly} above to match this file locally.</p>}
      <label className="genetic-check"><input type="checkbox" checked={forward} disabled={busy} onChange={event => setForward(event.target.checked)} />The file reports alleles on the forward reference strand. I verified its genome build.</label>
      <label className="genetic-check"><input type="checkbox" checked={consent} disabled={busy} onChange={event => setConsent(event.target.checked)} />I have permission to process this file for the primary person. I understand raw genetic calls can be wrong and this report must not guide medical decisions without professional review.</label>
      <label className="genetic-check"><input type="checkbox" checked={retain} disabled={busy} onChange={event => setRetain(event.target.checked)} />Retain the original privately for future reanalysis. I can remove it later while keeping my reports.</label>
      <p className="muted">Reports are retained on your Observatory. With retention off, the original file is processed in memory and is not stored. Phase, structural variants and polygenic risk are not interpreted.</p>
      <button className="btn" type="submit" disabled={busy || !file || !available || !forward || !consent}>{busy ? "Matching locally…" : "Create evidence report"}</button>
      {busy && <p role="status" aria-live="polite">Reading the file and matching supported alleles against the local reference. This can take up to two minutes.</p>}
    </form>
    {documents.length > 0 && <section className="card"><h3>Your genetic records</h3><ul className="lab-import-history">
      {documents.map(document => <li key={document.id}><a href={`/genetics/${document.id}`}>{document.file_name}</a>
        <span>{document.assembly} · {document.original_retained ? "Original retained" : "Reports only"}</span></li>)}
    </ul></section>}
  </div>;
}

const CATEGORY_LABELS: Record<string, string> = {
  all: "All classifications", pathogenic: "Pathogenic / likely pathogenic", benign: "Benign / likely benign",
  uncertain: "Uncertain significance", conflicting: "Conflicting classifications", other: "Other classifications",
};

export function GeneticDocumentView({ documentId }: { documentId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<GeneticDocumentDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [stars, setStars] = useState(0);
  const [page, setPage] = useState(0);
  const [deleting, setDeleting] = useState<"document" | "original" | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    get<GeneticDocumentDetail>(`/${documentId}`, abort.signal).then(setDetail)
      .catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [documentId]);
  const report = detail?.report;
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return (report?.annotations ?? []).filter(annotation => (category === "all" || annotation.category === category) &&
      annotation.review_stars >= stars && (!needle || [annotation.gene, annotation.conditions, annotation.variation_id, annotation.hgvs,
        `${annotation.chromosome}:${annotation.position}`, annotation.source_classification].some(value => value.toLocaleLowerCase().includes(needle))));
  }, [report, query, category, stars]);
  async function version(id: string) {
    setBusy(true); setError("");
    try { const report = await get<GeneticReport>(`/${documentId}/reports/${id}`); setDetail(current => current && ({ ...current, report })); setPage(0); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function reanalyze() {
    setBusy(true); setError(""); setMessage("");
    try {
      const report = await action<GeneticReport>(`/${documentId}/reanalyze`, { confirmed: true });
      const refreshed = await get<GeneticDocumentDetail>(`/${documentId}`);
      setDetail({ ...refreshed, report }); setPage(0);
      setMessage(detail?.reports.some(saved => saved.id === report.id) ? "This file already has a report for the current reference and analysis version." : "A new report version is ready. Earlier versions remain available.");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!deleting) return;
    setBusy(true); setError("");
    try {
      await action(`/${documentId}${deleting === "original" ? "/original" : ""}`, { confirmation: documentId }, "DELETE");
      if (deleting === "document") { router.push("/genetics"); router.refresh(); }
      else { setDetail(await get<GeneticDocumentDetail>(`/${documentId}`)); setDeleting(null); setMessage("The retained original was removed. Your report versions remain."); }
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function download() {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `healthsave-genetic-evidence-${report.reference.release_date}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (!detail || !report) return <div className="card">{error ? <p role="alert">{error}</p> : <p role="status">Opening your genetic evidence…</p>}<a href="/genetics">Back to genetic records</a></div>;
  const visible = filtered.slice(page * 50, (page + 1) * 50);
  return <article className="genetics">
    <header className="prov-intro"><a href="/genetics">← Genetic records</a><h2>Your variant evidence report</h2>
      <p>{detail.document.file_name} · {report.assembly} · ClinVar release {report.reference.release_date}</p>
      <p><strong>Evidence retrieval, not a diagnosis.</strong> Source classifications apply to variants and do not establish your personal disease risk. Confirm medically relevant findings with a genetics professional.</p>
      <div className="lab-import-actions lab-no-print"><button className="btn" onClick={download}>Download full report JSON</button><button className="btn btn-ghost" onClick={() => window.print()}>Print visible results</button>
        {detail.document.original_retained && <a className="btn btn-ghost" href={`/api/genetics/${documentId}/original`}>Download original</a>}
      </div>
    </header>
    {error && <p className="card" role="alert">{error}</p>}{message && <p className="card" role="status">{message}</p>}
    <section className="card"><h3>What was covered</h3><dl className="genetic-stats">
      <div><dt>Input rows</dt><dd>{report.input_counts.total_rows.toLocaleString()}</dd></div>
      <div><dt>Supported calls</dt><dd>{report.input_counts.accepted_loci.toLocaleString()}</dd></div>
      <div><dt>Loci with evidence matches</dt><dd>{report.matched_loci.toLocaleString()}</dd></div>
      <div><dt>Loci without a match</dt><dd>{report.unmatched_loci.toLocaleString()}</dd></div>
    </dl><p>No-calls: {report.input_counts.no_calls.toLocaleString()} · Filtered: {report.input_counts.filtered_rows.toLocaleString()} · Unsupported: {report.input_counts.unsupported_rows.toLocaleString()} · Duplicate rows: {report.input_counts.duplicate_rows.toLocaleString()}</p>
      <p><strong>Missing matches are not negative health results.</strong> This file and reference cover only part of genetic variation.</p>
      <details><summary>Quality, exclusions and interpretation limits</summary><ul>{[...report.warnings, ...report.limitations].map((line, index) => <li key={index}>{line}</li>)}</ul></details>
    </section>
    <section className="card genetic-versions lab-no-print"><h3>Report versions</h3>
      <label>Saved report<select value={report.id} disabled={busy} onChange={event => void version(event.target.value)}>{detail.reports.map(item => <option key={item.id} value={item.id}>{item.created_at.slice(0, 19).replace("T", " ")} UTC · ClinVar {item.reference_release} · {item.engine_version}</option>)}</select></label>
      {detail.document.original_retained ? <button className="btn btn-ghost" disabled={busy} onClick={() => void reanalyze()}>{busy ? "Working…" : "Reanalyze retained file with current reference"}</button> : <p>The original is not retained. Upload it again to analyze a newer reference.</p>}
    </section>
    <section className="card genetic-results"><h3>Matched variant annotations</h3>
      <div className="genetic-filters lab-no-print">
        <label>Search gene, condition or variant<input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label>
        <label>Source classification<select value={category} onChange={event => { setCategory(event.target.value); setPage(0); }}>{Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Minimum source review<select value={stars} onChange={event => { setStars(Number(event.target.value)); setPage(0); }}>{[0, 1, 2, 3, 4].map(value => <option key={value} value={value}>{value === 0 ? "All review statuses" : `${value}+ source review stars`}</option>)}</select></label>
      </div>
      <p>Showing {filtered.length ? page * 50 + 1 : 0}–{Math.min((page + 1) * 50, filtered.length)} of {filtered.length.toLocaleString()} filtered annotations from {report.annotations.length.toLocaleString()} saved annotations. {report.omitted_annotations > 0 && `${report.omitted_annotations.toLocaleString()} additional matches exceeded this report’s limit.`}</p>
      {filtered.length === 0 && <p>No annotations match these filters. This does not rule out a genetic condition.</p>}
      {visible.map(annotation => <section className="genetic-annotation" key={annotation.variation_id}>
        <div className="lab-import-heading"><h4>{annotation.gene || `ClinVar ${annotation.variation_id}`}</h4><span className="mono">{annotation.chromosome}:{annotation.position} {annotation.reference} → {annotation.alternate}</span></div>
        <p>Your input call: <strong>{annotation.genotype}</strong> · Alternate copies: {annotation.alternate_copies} · {annotation.call_quality === "file_filter_pass" ? "File filter: PASS; not clinically confirmed" : "Call quality not independently confirmed"}</p>
        <p><strong>ClinVar classification:</strong> {annotation.source_classification}{annotation.conflicting && " · Conflicting evidence"}</p>
        <p><strong>Source review:</strong> {annotation.review_stars}/4 · {annotation.source_review_status}</p>
        <p><strong>Conditions referenced by ClinVar:</strong> {annotation.conditions || "Not supplied"}</p>
        {annotation.details_truncated && <p>The source summary was shortened. Read the full public record for complete details.</p>}
        <details><summary>Matching and call details</summary><p>Exact {report.assembly} position and alternate allele. {report.input_format === "vcf" ? "VCF reference allele also matched." : "The input did not supply a reference allele; matching uses the confirmed forward strand."}</p>
          <p>HGVS: {annotation.hgvs || "Not supplied"} · File depth: {annotation.depth ?? "not supplied"} · File genotype quality: {annotation.genotype_quality ?? "not supplied"}</p>
        </details>
        <a href={annotation.source_url} target="_blank" rel="noreferrer">Open public ClinVar record ↗</a>
      </section>)}
      <div className="lab-import-actions lab-no-print"><button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous 50</button><button className="btn btn-ghost" disabled={(page + 1) * 50 >= filtered.length} onClick={() => setPage(value => value + 1)}>Next 50</button></div>
    </section>
    <section className="card"><h3>Evidence provenance</h3><p>Created {report.created_at} · Analysis {report.engine_version} · Index {report.reference.index_version}</p>
      <p>Input format: {report.input_format} · Assembly {report.assembly_in_file ? "verified against the file header" : "supplied by the importer"}</p>
      <p className="genetic-hash">Input SHA-256: {report.input_sha256}</p><p className="genetic-hash">ClinVar download SHA-256: {report.reference.sha256}</p>
      <p><a href="https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/" target="_blank" rel="noreferrer">What ClinVar review stars mean ↗</a></p>
      <p>This report does not combine genetic evidence and blood results into a disease score. <a href="/labs">Read your blood-test history separately →</a></p>
    </section>
    <GeneticReferencePanel />
    <section className="card lab-no-print"><h3>Your data controls</h3>
      {!deleting ? <div className="lab-import-actions">{detail.document.original_retained && <button className="btn btn-ghost" disabled={busy} onClick={() => setDeleting("original")}>Remove retained original…</button>}<button className="btn btn-ghost" disabled={busy} onClick={() => setDeleting("document")}>Delete this genetic record…</button></div> : <>
        <p>{deleting === "original" ? "Remove the retained DNA file? Your reports remain, but reanalysis will require uploading the file again." : `Delete this genetic record, its retained original and all ${detail.reports.length} report versions?`}</p>
        <p>This cannot be undone here. Downloaded copies and backups are separate.</p>
        <div className="lab-import-actions"><button className="btn btn-ghost" disabled={busy} onClick={() => setDeleting(null)}>Keep data</button><button className="btn" disabled={busy} onClick={() => void remove()}>Permanently delete {deleting === "original" ? "original" : "record"}</button></div>
      </>}
    </section>
  </article>;
}
