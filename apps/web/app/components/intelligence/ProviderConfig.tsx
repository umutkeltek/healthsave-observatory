"use client";

import type { IntelligenceView } from "../../lib/api";
import { CLOUD_PROVIDERS, OLLAMA_DEFAULT_BASE } from "./constants";
import { ConnectionTestPanel } from "./ConnectionTestPanel";
import type { ConnectionTest } from "./useConnectionTest";
import type { IntelligenceForm } from "./useIntelligenceForm";

// The local-model / cloud-provider card: provider + model + endpoint + key +
// advanced knobs, closed by the test/save action row (ConnectionTestPanel).
export function ProviderConfig({
  form,
  test,
  view,
}: {
  form: IntelligenceForm;
  test: ConnectionTest;
  view: IntelligenceView;
}) {
  const { mode } = form;
  return (
    <section className="intel-card">
      <h3 className="intel-h">{mode === "local" ? "Local model" : "Cloud provider"}</h3>

      {mode === "cloud" && (
        <label className="field">
          <span className="field-label">Provider</span>
          <select
            className="field-input"
            value={form.provider}
            onChange={(e) => form.pickProvider(e.target.value)}
          >
            {CLOUD_PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="field">
        <span className="field-label">Model</span>
        <input
          className="field-input"
          value={form.model}
          onChange={(e) => form.setModel(e.target.value)}
          placeholder={mode === "local" ? "llama3.1:8b" : "provider/model"}
          spellCheck={false}
        />
      </label>

      {mode === "local" && (
        <>
          <label className="field">
            <span className="field-label">Base URL</span>
            <input
              className="field-input"
              value={form.baseUrl}
              onChange={(e) => form.setBaseUrl(e.target.value)}
              placeholder={OLLAMA_DEFAULT_BASE}
              spellCheck={false}
            />
            <span className="field-hint">
              Point at a model on your own machine. New here?{" "}
              <button
                type="button"
                className="intel-link"
                disabled={form.pending}
                onClick={form.detect}
              >
                Detect a local model
              </button>{" "}
              or run <code>deploy/local-ai/setup-local-ai.sh</code> to install one.
            </span>
          </label>
          {form.detectMsg && (
            <div className={`test-result ${form.detectMsg.ok ? "ok" : "bad"}`}>
              {form.detectMsg.ok ? "✓ " : "✗ "}
              {form.detectMsg.text}
            </div>
          )}
        </>
      )}

      {mode === "cloud" && (
        <label className="field">
          <span className="field-label">API key</span>
          <input
            className="field-input"
            type="password"
            value={form.apiKey}
            onChange={(e) => form.setApiKey(e.target.value)}
            placeholder={
              view.primary?.key_last4
                ? `saved ${view.primary.key_last4} — leave blank to keep`
                : "sk-…"
            }
            autoComplete="off"
            spellCheck={false}
          />
          <span className="field-hint">
            Stored encrypted on your host. It is never shown again and never returned by the API.
          </span>
        </label>
      )}

      {mode === "cloud" && (
        <>
          <button
            type="button"
            className="intel-link"
            onClick={() => form.setAdvanced((v) => !v)}
          >
            {form.advanced ? "Hide" : "Show"} advanced (temperature, max tokens, redaction)
          </button>
          {form.advanced && (
            <div className="adv-grid">
              <label className="field">
                <span className="field-label">Temperature</span>
                <input
                  className="field-input"
                  value={form.temperature}
                  onChange={(e) => form.setTemperature(e.target.value)}
                  placeholder="0.3"
                  inputMode="decimal"
                />
              </label>
              <label className="field">
                <span className="field-label">Max tokens</span>
                <input
                  className="field-input"
                  value={form.maxTokens}
                  onChange={(e) => form.setMaxTokens(e.target.value)}
                  placeholder="1000"
                  inputMode="numeric"
                />
              </label>
              <label className="field field-check">
                <input
                  type="checkbox"
                  checked={form.redact}
                  onChange={(e) => form.setRedact(e.target.checked)}
                />
                <span>Redact identifiers from prompts before they leave (recommended)</span>
              </label>
            </div>
          )}
        </>
      )}

      <ConnectionTestPanel form={form} test={test} />
    </section>
  );
}
