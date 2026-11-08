"use client";

import { useState, useTransition } from "react";

import type { CreateMomentPayload } from "../lib/api";
import { createMomentAction } from "../lib/actions";
import { runAction } from "../lib/session";

const KINDS: { key: string; label: string }[] = [
  { key: "illness", label: "Illness" },
  { key: "alcohol", label: "Alcohol" },
  { key: "late_meal", label: "Late meal" },
  { key: "travel", label: "Travel" },
  { key: "medication_change", label: "Medication change" },
  { key: "supplement_change", label: "Supplement change" },
  { key: "hard_training", label: "Hard training" },
  { key: "stress", label: "Stress" },
  { key: "caffeine", label: "Caffeine" },
  { key: "injury", label: "Injury" },
  { key: "menstrual", label: "Menstrual" },
  { key: "custom", label: "Other" },
];

const GRADES = ["mild", "moderate", "severe"] as const;

function kindLabel(kind: string): string {
  return KINDS.find((k) => k.key === kind)?.label ?? kind;
}

// The outcome of the last submit. Its kind - not its wording - decides how it
// renders, so a backend detail or the signed-out message is never styled as a
// success.
export type MomentStatus = { kind: "saved" } | { kind: "error"; message: string };

export function MomentStatusLine({ status }: { status: MomentStatus | null }) {
  if (!status) return null;
  return status.kind === "saved" ? (
    <span className="meta" role="status">
      Moment added.
    </span>
  ) : (
    <span className="exp-error" role="status">
      {status.message}
    </span>
  );
}

export function MomentForm() {
  const [kind, setKind] = useState("custom");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [grade, setGrade] = useState("");
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<MomentStatus | null>(null);

  return (
    <article className="card">
      <h2>Add a moment</h2>
      <div className="field-grid">
        <label className="field-label">
          Kind
          <select className="field-input" value={kind} onChange={(event) => setKind(event.target.value)}>
            {KINDS.map((k) => (
              <option value={k.key} key={k.key}>{k.label}</option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Title
          <input
            className="field-input"
            type="text"
            placeholder={`E.g. "Late flight home" for ${kindLabel(kind)}`}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="field-label">
          Severity (optional)
          <select className="field-input" value={grade} onChange={(event) => setGrade(event.target.value)}>
            <option value="">—</option>
            {GRADES.map((g) => (
              <option value={g} key={g}>{g}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="field-label" style={{ marginTop: 12 }}>
        Note (optional)
        <input
          className="field-input"
          type="text"
          placeholder="Any detail that helps explain the timing..."
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <div className="exp-action" style={{ marginTop: 12 }}>
        <button
          className="btn"
          type="button"
          disabled={pending || !title.trim()}
          onClick={() =>
            startTransition(async () => {
              const payload: CreateMomentPayload = {
                kind,
                title: title.trim(),
                start_at: new Date().toISOString(),
              };
              if (grade) payload.grade = grade;
              if (note.trim()) payload.note = note.trim();
              const result = await runAction(() => createMomentAction(payload));
              if (result.ok) {
                setTitle("");
                setNote("");
                setGrade("");
                setStatus({ kind: "saved" });
              } else {
                setStatus({ kind: "error", message: result.error ?? "Could not add this moment." });
              }
            })
          }
        >
          {pending ? "Adding…" : "Add moment"}
        </button>
        <MomentStatusLine status={status} />
      </div>
    </article>
  );
}
