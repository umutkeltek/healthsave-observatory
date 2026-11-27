"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Preview = { file_name: string; linked_result_count: number; explanation: string };

export function DeleteLabDocument({ documentId }: { documentId: string }) {
  const router = useRouter();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [deleteResults, setDeleteResults] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function prepare() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/lab-imports/${documentId}/deletion`, { cache: "no-store" });
      if (!response.ok) throw new Error("The deletion preview could not be loaded.");
      setPreview(await response.json());
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/lab-imports/${documentId}`, { method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: documentId, delete_results: deleteResults }) });
      if (!response.ok) throw new Error("The document could not be deleted. It can be retried.");
      // Stay on "Deleting…" until the document list replaces this screen.
      router.push("/labs/import"); router.refresh();
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  return <section className="card lab-no-print">
    {error && <p role="alert">{error}</p>}
    {!preview ? <button className="btn btn-ghost" disabled={busy} onClick={() => void prepare()}>Delete this document…</button> : <>
      <h3>Delete {preview.file_name}?</h3><p>{preview.explanation}</p>
      <label className="lab-review-confirm"><input type="checkbox" checked={deleteResults} disabled={busy}
        onChange={event => setDeleteResults(event.target.checked)} />Also delete {preview.linked_result_count} result{preview.linked_result_count === 1 ? "" : "s"} last written by this import.</label>
      <div className="lab-import-actions"><button className="btn btn-ghost" disabled={busy} onClick={() => setPreview(null)}>Keep document</button>
        <button className="btn" disabled={busy} onClick={() => void remove()}>{busy ? "Deleting…" : "Permanently delete"}</button></div>
    </>}
  </section>;
}
