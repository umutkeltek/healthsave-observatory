"use client";

import { useState, useTransition } from "react";

import type { CreateMomentPayload } from "../lib/api";
import { createMomentAction } from "../lib/actions";

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

export function MomentForm() {
  const [kind, setKind] = useState("custom");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [grade, setGrade] = useState("");
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<string | null>(null);

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
              const result = await createMomentAction(payload);
              if (result.ok) {
                setTitle("");
                setNote("");
                setGrade("");
                setStatus("Moment added.");
              } else {
                setStatus(result.error ?? "Could not add this moment.");
              }
            })
          }
        >
          {pending ? "Adding…" : "Add moment"}
        </button>
        {status && (
          <span className={status.includes("Could not") ? "exp-error" : "meta"} role="status">
            {status}
          </span>
        )}
      </div>
    </article>
  );
}
