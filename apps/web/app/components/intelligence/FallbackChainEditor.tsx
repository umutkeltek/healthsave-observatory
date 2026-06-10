"use client";

import type { FallbackDraft } from "./constants";
import type { IntelligenceForm } from "./useIntelligenceForm";

function updateFallback(
  setter: React.Dispatch<React.SetStateAction<FallbackDraft[]>>,
  index: number,
  patch: Partial<FallbackDraft>,
) {
  setter((prev) => prev.map((f, i) => (i === index ? { ...f, ...patch } : f)));
}

export function FallbackChainEditor({ form }: { form: IntelligenceForm }) {
  const { fallbacks, setFallbacks } = form;
  return (
    <section className="intel-card">
      <h3 className="intel-h">Fallbacks</h3>
      <p className="intel-sub">
        Tried in order if the primary fails. Free OpenRouter models are flaky individually, so a
        short chain is what makes them reliable.
      </p>
      {fallbacks.map((fb, i) => (
        // biome-ignore lint: positional rows; drafts have no stable identity
        <div className="fb-row" key={i}>
          <input
            className="field-input"
            value={fb.provider}
            onChange={(e) => updateFallback(setFallbacks, i, { provider: e.target.value })}
            placeholder="provider"
            spellCheck={false}
          />
          <input
            className="field-input fb-model"
            value={fb.model}
            onChange={(e) => updateFallback(setFallbacks, i, { model: e.target.value })}
            placeholder="provider/model"
            spellCheck={false}
          />
          <input
            className="field-input"
            type="password"
            value={fb.apiKey}
            onChange={(e) => updateFallback(setFallbacks, i, { apiKey: e.target.value })}
            placeholder="key (optional)"
            autoComplete="off"
          />
          <button
            type="button"
            className="fb-del"
            onClick={() => setFallbacks((p) => p.filter((_, j) => j !== i))}
            aria-label="Remove fallback"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="intel-link"
        onClick={() => setFallbacks((p) => [...p, { provider: "openrouter", model: "", apiKey: "" }])}
      >
        + Add fallback
      </button>
    </section>
  );
}
