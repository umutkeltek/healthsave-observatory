"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { LabImportCatalog, LabImportDraft, LabImportIndex, LabImportReceipt, ReviewRow } from "../lib/labImportTypes";
import { applyReviewDetails, editReviewRow, newReviewRow, pdfReviewExcerpt, REVIEW_DEFAULTS } from "../lib/labReview";
import { DeleteLabDocument } from "./DeleteLabDocument";
import { newUploadId } from "../lib/uploadIdentity";

type Issue = { row: number; field: string | null; message: string };
async function readResponse<T>(response: Response): Promise<T> {
  const value = await response.json();
  if (!response.ok) {
    const detail = value.detail;
    const message = typeof detail === "string" ? detail : detail?.message ?? "This request could not be completed.";
    throw Object.assign(new Error(message), { issues: detail?.errors ?? [] });
  }
  return value as T;
}

export function LabImport({ documentId }: { documentId?: string }) {
  const router = useRouter();
  const [draft, setDraft] = useState<LabImportDraft | null>(null);
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [catalog, setCatalog] = useState<LabImportCatalog["markers"]>([]);
  const [history, setHistory] = useState<LabImportIndex["documents"]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [busy, setBusy] = useState<string | null>(documentId ? "Opening your draft…" : null);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [date, setDate] = useState("");
  const [lab, setLab] = useState("");
  const attempt = useRef<{ file: File; id: string } | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const dirty = useRef(false);
  const errorBox = useRef<HTMLDivElement>(null);
  // The server-rendered picker can be tapped before this script runs; a file chosen then
  // would never upload, so keep it disabled until the page can handle the choice.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty.current) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  useEffect(() => {
    if (error) {
      errorBox.current?.focus();
      errorBox.current?.scrollIntoView({ block: "center" });
    }
  }, [error]);

  function focusResult(index: number, field = "loinc") {
    const target = document.getElementById(`lab-row-${index}-${field}`)
      ?? document.getElementById(`lab-row-${index}`);
    target?.focus();
    target?.scrollIntoView({ block: "center" });
  }

  useEffect(() => {
    const abort = new AbortController();
    const options = { signal: abort.signal, cache: "no-store" as const };
    fetch("/api/lab-imports/catalog", options).then(readResponse<LabImportCatalog>).then(v => setCatalog(v.markers)).catch(() => {});
    const request = documentId ? `/api/lab-imports/${encodeURIComponent(documentId)}` : "/api/lab-imports";
    fetch(request, options).then(readResponse<LabImportDraft | LabImportIndex>).then(value => {
      if ("documents" in value) { setHistory(value.documents); setNextCursor(value.next_cursor ?? null); }
      else if (value.status === "committed") router.replace(`/labs/import/${value.id}/report`);
      else { setDraft(value); setRows(value.rows.map(row => ({ ...REVIEW_DEFAULTS, ...row, confirmed: false }))); }
      setBusy(null);
    }).catch(e => { if (!abort.signal.aborted) { setError(e.message); setBusy(null); } });
    return () => abort.abort();
  }, [documentId, router]);
  async function loadMore() {
    if (!nextCursor || loadingHistory) return;
    setLoadingHistory(true); setError("");
    try {
      const value = await fetch(`/api/lab-imports?${new URLSearchParams({ cursor: nextCursor })}`, { cache: "no-store" }).then(readResponse<LabImportIndex>);
      setHistory(current => [...new Map([...current, ...value.documents].map(item => [item.id, item])).values()]);
      setNextCursor(value.next_cursor ?? null);
    } catch (e) { setError((e as Error).message); }
    finally { setLoadingHistory(false); }
  }

  async function upload(file?: File) {
    file ??= attempt.current?.file;
    if (!file) return;
    setError(""); setIssues([]); setCanRetry(false);
    if (file.size === 0 || file.size > 5 * 1024 * 1024 || !/\.(csv|pdf)$/i.test(file.name)) {
      setError("Choose a non-empty CSV or PDF no larger than 5 MB."); return;
    }
    setBusy("Reading your report on this Observatory. Scanned pages can take up to 90 seconds…");
    try {
      if (!attempt.current || attempt.current.file !== file) attempt.current = { file, id: newUploadId() };
      const value = await readResponse<LabImportDraft>(await fetch("/api/lab-imports", {
        method: "POST", headers: { "X-Upload-ID": attempt.current.id, "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" }, body: file,
      }));
      router.push(`/labs/import/${value.id}`);
    } catch (e) { setError(e instanceof Error ? e.message : "The document could not be read."); setCanRetry(true); }
    finally { setBusy(null); }
  }

  function update(index: number, field: keyof ReviewRow, value: string | boolean) {
    dirty.current = true;
    setRows(current => current.map((row, i) => i === index ? {
      ...editReviewRow(row, field, value),
      ...(field === "loinc" && catalog.find(m => m.loinc === value) ? { marker_name: catalog.find(m => m.loinc === value)!.name } : {}),
    } : row));
    setIssues([]);
  }

  async function save() {
    if (!draft) return;
    setBusy("Saving your confirmed results…"); setError(""); setIssues([]);
    try {
      const receipt = await readResponse<LabImportReceipt>(await fetch(`/api/lab-imports/${draft.id}/commit`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows }),
      }));
      dirty.current = false;
      router.push(receipt.report_url);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The results could not be saved.");
      setIssues((e as { issues?: Issue[] }).issues ?? []);
    } finally { setBusy(null); }
  }

  const confirmed = rows.filter(r => r.confirmed).length;
  return <div className="lab-import">
    <div className="prov-intro labs-intro">
      <a href="/labs">← Blood tests</a>
      <h2>{draft ? "Review your blood tests" : "Bring your blood tests together"}</h2>
      <p>{draft ? "Compare each result with the original. Nothing enters your health record until you confirm and save." : "Import a CSV or PDF from your lab. Extraction and review happen on your own Observatory."}</p>
    </div>
    {error && <div ref={errorBox} tabIndex={-1} className="card lab-import-error" role="alert"><strong>{error}</strong>
      {issues.length > 0 && <ul>{issues.map((issue, i) => <li key={i}><button className="btn btn-ghost" onClick={() => focusResult(issue.row, issue.field ?? "loinc")}>Result {issue.row + 1}{issue.field ? `, ${issue.field.replaceAll("_", " ")}` : ""}: {issue.message}</button></li>)}</ul>}
      {canRetry && <button className="btn btn-ghost" disabled={!!busy} onClick={() => void upload()}>Retry this upload</button>}
    </div>}
    {busy && <p className="card" role="status" aria-live="polite">{busy}</p>}
    {!draft && !documentId && <>
      <section className="card lab-import-upload">
        <h3>Choose a lab report</h3>
        <p>CSV, text PDF, or scanned PDF · up to 5 MB and 12 pages</p>
        <label className="lab-import-file">Report file
          <input type="file" accept=".csv,.pdf,text/csv,application/pdf" disabled={!!busy || !ready} onChange={e => { void upload(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        <p className="muted">The original is retained privately with your records. No cloud AI service receives it. A scan may need corrections.</p>
        <a href="/labs/template.csv" download>Download the CSV template</a>
      </section>
      {history.length > 0 && <section className="card"><h3>Your documents</h3><ul className="lab-import-history">
        {history.map(item => <li key={item.id}><a href={`/labs/import/${item.id}${item.committed_at ? "/report" : ""}`}>{item.file_name}</a><span>{item.committed_at ? "Saved report" : "Review needed"}</span></li>)}
      </ul>{nextCursor && <button className="btn btn-ghost" disabled={loadingHistory} onClick={() => void loadMore()}>{loadingHistory ? "Loading older documents…" : "Load older documents"}</button>}</section>}
    </>}
    {draft && <>
      <section className="card lab-import-source">
        <div className="lab-import-heading"><h3>{draft.file_name}</h3><a className="btn btn-ghost" href={`/api/lab-imports/${draft.id}/original`}>Download original</a></div>
        <ul>{draft.warnings.map(w => <li key={w}>{w}</li>)}</ul>
        <details><summary>Read extracted source text</summary>{draft.pages.map(page => <section key={page.page}>
          <h4>Page {page.page}{page.method === "ocr" ? " · read with OCR" : ""}</h4><pre className="lab-source-text">{page.text || "No text was detected. Use the original document to enter results manually."}</pre>
        </section>)}</details>
      </section>
      <fieldset className="card lab-import-bulk" disabled={!!busy}>
        <legend>Details shared by these results</legend>
        <label>Sample date<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
        <label>Performing lab<input value={lab} maxLength={160} onChange={e => setLab(e.target.value)} placeholder="As printed on the report" /></label>
        <button className="btn btn-ghost" type="button" disabled={!date && !lab} onClick={() => { dirty.current = true; setIssues([]); setRows(current => applyReviewDetails(current, date, lab)); }}>Apply to all results</button>
        <p>Use the date the sample was taken. Applying these details clears previous confirmations.</p>
      </fieldset>
      <datalist id="lab-test-codes">{catalog.map(m => <option key={m.loinc} value={m.loinc}>{m.name} ({m.unit})</option>)}</datalist>
      <div className="lab-import-actions">
        <span role="status">{confirmed} of {rows.length} confirmed</span>
        <button className="btn btn-ghost" disabled={!!busy || confirmed === rows.length} onClick={() => focusResult(rows.findIndex(row => !row.confirmed))}>Next unchecked result</button>
      </div>
      <div className="lab-review-list">{rows.map((row, index) => {
        const rowIssues = issues.filter(i => i.row === index);
        const excerpt = pdfReviewExcerpt(row.row_id, draft.pages);
        const fieldProps = (field: keyof ReviewRow) => ({
          id: `lab-row-${index}-${field}`,
          "aria-invalid": rowIssues.some(issue => issue.field === field) || undefined,
          "aria-describedby": rowIssues.some(issue => issue.field === field) ? `lab-row-${index}-errors` : undefined,
        });
        return <fieldset id={`lab-row-${index}`} tabIndex={-1} className={`card lab-review-row${row.confirmed ? " is-confirmed" : ""}`} key={row.row_id} disabled={!!busy}>
          <legend>Result {index + 1}{row.marker_name ? ` · ${row.marker_name}` : ""}</legend>
          <div className="lab-import-heading"><span>{row.row_id.startsWith("manual-") ? "Entered manually; source location not recorded" : row.row_id.startsWith("p") ? `Extracted from page ${row.row_id.match(/^p(\d+)/)?.[1]}` : `CSV row ${row.row_id.replace("csv-", "")}`}</span>
            <button className="btn btn-ghost" type="button" onClick={() => { dirty.current = true; setIssues([]); setRows(current => current.filter((_, i) => i !== index)); }} aria-label={`Remove result ${index + 1}`}>Remove</button></div>
          {excerpt && <details><summary>Compare extracted source line</summary><pre className="lab-source-text">{excerpt}</pre><p className="muted">Extraction can contain mistakes. Check the original document too.</p></details>}
          <div className="lab-review-fields">
            <label>Test code<input {...fieldProps("loinc")} autoCapitalize="none" autoCorrect="off" spellCheck={false} list="lab-test-codes" value={row.loinc} onChange={e => update(index, "loinc", e.target.value)} placeholder="Choose a test or enter its LOINC" maxLength={20} /></label>
            <label>Test name<input {...fieldProps("marker_name")} value={row.marker_name} onChange={e => update(index, "marker_name", e.target.value)} maxLength={160} /></label>
            <label>Result<input {...fieldProps("value")} autoCorrect="off" spellCheck={false} value={row.value} onChange={e => update(index, "value", e.target.value)} placeholder="e.g. 12 or <0.5" maxLength={80} /></label>
            <label>Unit<input {...fieldProps("unit")} autoCapitalize="none" autoCorrect="off" spellCheck={false} value={row.unit} onChange={e => update(index, "unit", e.target.value)} placeholder="e.g. ng/mL" maxLength={80} /></label>
            <label>Range low<input {...fieldProps("reference_low")} value={row.reference_low} onChange={e => update(index, "reference_low", e.target.value)} placeholder="Leave blank if absent" maxLength={80} /></label>
            <label>Range high<input {...fieldProps("reference_high")} value={row.reference_high} onChange={e => update(index, "reference_high", e.target.value)} placeholder="Leave blank if absent" maxLength={80} /></label>
            <label>Sample date / time<input {...fieldProps("specimen_datetime")} value={row.specimen_datetime} onChange={e => update(index, "specimen_datetime", e.target.value)} placeholder="YYYY-MM-DD" maxLength={80} /></label>
            <label>Performing lab<input {...fieldProps("lab")} value={row.lab} onChange={e => update(index, "lab", e.target.value)} maxLength={160} /></label>
          </div>
          {rowIssues.length > 0 && <ul id={`lab-row-${index}-errors`} className="lab-import-error">{rowIssues.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul>}
          <label className="lab-review-confirm"><input {...fieldProps("confirmed")} type="checkbox" checked={row.confirmed} onChange={e => update(index, "confirmed", e.target.checked)} />I checked this result, unit, date, lab and range against the original.</label>
        </fieldset>;
      })}</div>
      <div className="lab-import-actions">
        <button className="btn btn-ghost" disabled={!!busy || rows.length >= 250} onClick={() => { dirty.current = true; setRows(current => [...current, newReviewRow()]); }}>Add a result</button>
        <button className="btn btn-ghost" disabled={!!busy || confirmed === rows.length} onClick={() => focusResult(rows.findIndex(row => !row.confirmed))}>Next unchecked result</button>
        <button className="btn" disabled={!!busy || rows.length === 0 || confirmed !== rows.length} onClick={() => void save()}>Save {rows.length} result{rows.length === 1 ? "" : "s"}</button>
      </div>
      <p className="muted">Edits are lost if you leave or reload before saving. Your original upload remains available to review again.</p>
      <DeleteLabDocument documentId={draft.id} />
    </>}
  </div>;
}
