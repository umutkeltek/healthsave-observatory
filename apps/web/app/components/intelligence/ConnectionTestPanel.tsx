"use client";

import { useState } from "react";
import type { ConnectionTest } from "./useConnectionTest";
import type { IntelligenceForm } from "./useIntelligenceForm";

// The provider card's action row (test + save) and the probe outcome lines.
export function ConnectionTestPanel({
  form,
  test,
}: {
  form: IntelligenceForm;
  test: ConnectionTest;
}) {
  // Test, save, detect and consent share the form's one pending flag; only the
  // button that started the request says so ("Testing…" must not read "Saving…").
  const [started, setStarted] = useState<"test" | "save" | null>(null);
  if (!form.pending && started) setStarted(null);
  return (
    <>
      <div className="intel-actions">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={form.pending}
          onClick={() => {
            setStarted("test");
            test.runTest(form.buildConnectionInput());
          }}
        >
          {form.pending && started === "test" ? "Testing…" : "Test connection"}
        </button>
        <button
          type="button"
          className="btn"
          disabled={form.pending}
          onClick={() => {
            setStarted("save");
            form.save();
          }}
        >
          {form.pending && started === "save" ? "Saving…" : "Save"}
        </button>
      </div>

      {test.testResult && (
        <div className={`test-result ${test.testResult.ok ? "ok" : "bad"}`}>
          {test.testResult.ok
            ? `✓ Reached ${test.testResult.model} (${test.testResult.destination})${
                test.testResult.latency_ms != null ? ` · ${test.testResult.latency_ms}ms` : ""
              }`
            : `✗ ${test.testResult.error ?? "no response"}`}
        </div>
      )}
      {test.testErr && <div className="test-result bad">✗ {test.testErr}</div>}
    </>
  );
}
