"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import {
  applyIntelligenceAction,
  consentAction,
  testConnectionAction,
} from "../lib/actions";
import type {
  ApplyIntelligencePayload,
  ConnectionInputPayload,
  IntelligenceView,
  IntelMode,
  TestConnectionResult,
} from "../lib/api";

// Known cloud providers + a sensible default model. The user can still type any
// litellm route; these just make the common path one click.
const CLOUD_PROVIDERS = [
  { id: "deepseek", label: "DeepSeek", model: "deepseek/deepseek-chat" },
  { id: "openai", label: "OpenAI", model: "openai/gpt-4o-mini" },
  { id: "anthropic", label: "Anthropic", model: "anthropic/claude-sonnet" },
  { id: "gemini", label: "Google Gemini", model: "gemini/gemini-2.5-flash" },
  { id: "openrouter", label: "OpenRouter", model: "openrouter/openai/gpt-oss-120b:free" },
] as const;

const OLLAMA_DEFAULT_BASE = "http://ollama:11434";

type FallbackDraft = { provider: string; model: string; apiKey: string };

const MODE_CARDS: { id: IntelMode; title: string; blurb: string }[] = [
  {
    id: "off",
    title: "Off",
    blurb: "No narrator. Findings are computed on-device by the statistical engine. Nothing leaves.",
  },
  {
    id: "local",
    title: "Local",
    blurb: "A model on your own machine (Ollama) writes the briefs. Still nothing leaves the host.",
  },
  {
    id: "cloud",
    title: "Cloud",
    blurb: "Your own provider key. Only redacted, derived findings leave — never raw health data.",
  },
];

export function IntelligenceSettings({ initial }: { initial: IntelligenceView | null }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  // Unconfigured backend → a minimal off-state so the page still renders.
  const view: IntelligenceView = initial ?? {
    mode: "off",
    managed_by_env: false,
    env_provider: null,
    allow_cloud_egress: false,
    redact_cloud_prompts: true,
    revision: 0,
    consent: { granted: false, version: null, at: null },
    primary: null,
    fallback: [],
  };

  const [mode, setMode] = useState<IntelMode>(view.mode);
  const [provider, setProvider] = useState(
    view.primary?.provider ?? (view.mode === "local" ? "ollama" : "deepseek"),
  );
  const [model, setModel] = useState(
    view.primary?.model ?? CLOUD_PROVIDERS[0].model,
  );
  const [baseUrl, setBaseUrl] = useState(view.primary?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [redact, setRedact] = useState(view.redact_cloud_prompts);
  const [fallbacks, setFallbacks] = useState<FallbackDraft[]>(
    view.fallback.map((f) => ({ provider: f.provider ?? "openrouter", model: f.model, apiKey: "" })),
  );
  const [advanced, setAdvanced] = useState(false);
  const [temperature, setTemperature] = useState("");
  const [maxTokens, setMaxTokens] = useState("");

  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);
  const [testErr, setTestErr] = useState<string | null>(null);
  const [consentChecked, setConsentChecked] = useState(false);

  const savedCloud = view.mode === "cloud" && view.primary !== null;
  const consentGranted = view.consent.granted;

  function pickProvider(id: string) {
    setProvider(id);
    const preset = CLOUD_PROVIDERS.find((p) => p.id === id);
    if (preset) setModel(preset.model);
  }

  function buildPayload(): ApplyIntelligencePayload {
    if (mode === "off") return { mode: "off" };
    const primary: ApplyIntelligencePayload["primary"] = {
      provider: mode === "local" ? "ollama" : provider,
      model: model.trim(),
    };
    if (mode === "local") primary.base_url = baseUrl.trim() || OLLAMA_DEFAULT_BASE;
    else if (baseUrl.trim()) primary.base_url = baseUrl.trim();
    if (apiKey.trim()) primary.api_key = apiKey.trim();
    if (advanced && temperature.trim()) primary.temperature = Number(temperature);
    if (advanced && maxTokens.trim()) primary.max_tokens = Number(maxTokens);

    const cleanFallbacks: ConnectionInputPayload[] = fallbacks
      .filter((f) => f.model.trim())
      .map((f) => {
        const entry: ConnectionInputPayload = { provider: f.provider.trim(), model: f.model.trim() };
        if (f.apiKey.trim()) entry.api_key = f.apiKey.trim();
        return entry;
      });

    return {
      mode,
      primary,
      redact_cloud_prompts: redact,
      fallback: mode === "cloud" ? cleanFallbacks : [],
    };
  }

  function save() {
    setSaveMsg(null);
    startTransition(async () => {
      const result = await applyIntelligenceAction(buildPayload());
      if (result.ok) {
        setApiKey("");
        setFallbacks((prev) => prev.map((f) => ({ ...f, apiKey: "" })));
        setSaveMsg({ ok: true, text: "Saved. The narrator picks this up on its next run." });
        router.refresh();
      } else {
        setSaveMsg({ ok: false, text: result.error ?? "Save failed." });
      }
    });
  }

  function runTest() {
    setTestResult(null);
    setTestErr(null);
    startTransition(async () => {
      const result = await testConnectionAction({
        provider: mode === "local" ? "ollama" : provider,
        model: model.trim(),
        base_url:
          mode === "local" ? baseUrl.trim() || OLLAMA_DEFAULT_BASE : baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
      });
      if (result.ok && result.result) setTestResult(result.result);
      else setTestErr(result.error ?? "Test failed.");
    });
  }

  function toggleConsent(grant: boolean) {
    startTransition(async () => {
      const result = await consentAction({
        granted: grant,
        consent_version: grant ? new Date().toISOString().slice(0, 10) : null,
      });
      if (result.ok) {
        setConsentChecked(false);
        router.refresh();
      } else {
        setSaveMsg({ ok: false, text: result.error ?? "Consent update failed." });
      }
    });
  }

  const whatLeaves = useMemo(() => leavesCopy(mode, redact), [mode, redact]);

  return (
    <div className="intel">
      {view.managed_by_env && (
        <div className="intel-banner">
          <strong>Managed by environment.</strong> The narrator is currently running from
          deploy-time configuration{view.env_provider ? ` (${view.env_provider})` : ""}. Saving
          here writes to the database and takes over — your edits become the source of truth.
        </div>
      )}

      <section className="intel-card">
        <h3 className="intel-h">Mode</h3>
        <div className="mode-grid">
          {MODE_CARDS.map((card) => (
            <button
              key={card.id}
              type="button"
              className={`mode-card ${mode === card.id ? "sel" : ""}`}
              onClick={() => setMode(card.id)}
              aria-pressed={mode === card.id}
            >
              <span className="mode-card-title">{card.title}</span>
              <span className="mode-card-blurb">{card.blurb}</span>
            </button>
          ))}
        </div>
      </section>

      {mode !== "off" && (
        <section className="intel-card">
          <h3 className="intel-h">{mode === "local" ? "Local model" : "Cloud provider"}</h3>

          {mode === "cloud" && (
            <label className="field">
              <span className="field-label">Provider</span>
              <select
                className="field-input"
                value={provider}
                onChange={(e) => pickProvider(e.target.value)}
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
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={mode === "local" ? "llama3.1:8b" : "provider/model"}
              spellCheck={false}
            />
          </label>

          {mode === "local" && (
            <label className="field">
              <span className="field-label">Base URL</span>
              <input
                className="field-input"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={OLLAMA_DEFAULT_BASE}
                spellCheck={false}
              />
            </label>
          )}

          {mode === "cloud" && (
            <label className="field">
              <span className="field-label">API key</span>
              <input
                className="field-input"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
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
                onClick={() => setAdvanced((v) => !v)}
              >
                {advanced ? "Hide" : "Show"} advanced (temperature, max tokens, redaction)
              </button>
              {advanced && (
                <div className="adv-grid">
                  <label className="field">
                    <span className="field-label">Temperature</span>
                    <input
                      className="field-input"
                      value={temperature}
                      onChange={(e) => setTemperature(e.target.value)}
                      placeholder="0.3"
                      inputMode="decimal"
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">Max tokens</span>
                    <input
                      className="field-input"
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(e.target.value)}
                      placeholder="1000"
                      inputMode="numeric"
                    />
                  </label>
                  <label className="field field-check">
                    <input
                      type="checkbox"
                      checked={redact}
                      onChange={(e) => setRedact(e.target.checked)}
                    />
                    <span>Redact identifiers from prompts before they leave (recommended)</span>
                  </label>
                </div>
              )}
            </>
          )}

          <div className="intel-actions">
            <button type="button" className="btn btn-ghost" disabled={pending} onClick={runTest}>
              {pending ? "Testing…" : "Test connection"}
            </button>
            <button type="button" className="btn" disabled={pending} onClick={save}>
              {pending ? "Saving…" : "Save"}
            </button>
          </div>

          {testResult && (
            <div className={`test-result ${testResult.ok ? "ok" : "bad"}`}>
              {testResult.ok
                ? `✓ Reached ${testResult.model} (${testResult.destination})${
                    testResult.latency_ms != null ? ` · ${testResult.latency_ms}ms` : ""
                  }`
                : `✗ ${testResult.error ?? "no response"}`}
            </div>
          )}
          {testErr && <div className="test-result bad">✗ {testErr}</div>}
        </section>
      )}

      {mode === "cloud" && (
        <section className="intel-card">
          <h3 className="intel-h">Fallbacks</h3>
          <p className="intel-sub">
            Tried in order if the primary fails. Free OpenRouter models are flaky individually, so a
            short chain is what makes them reliable.
          </p>
          {fallbacks.map((fb, i) => (
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
            onClick={() =>
              setFallbacks((p) => [...p, { provider: "openrouter", model: "", apiKey: "" }])
            }
          >
            + Add fallback
          </button>
        </section>
      )}

      <section className="intel-card intel-leaves">
        <h3 className="intel-h">What leaves your host</h3>
        <p className="brief-body">{whatLeaves}</p>
        <div className="assurance">Raw observations never leave the host — in any mode.</div>
      </section>

      {savedCloud && (
        <section className="intel-card intel-consent">
          <h3 className="intel-h">Cloud egress consent</h3>
          {consentGranted ? (
            <>
              <div className="consent-state ok">
                ✓ Granted{view.consent.at ? ` on ${view.consent.at.slice(0, 10)}` : ""}. Redacted
                findings may be sent to your cloud provider.
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={pending}
                onClick={() => toggleConsent(false)}
              >
                Revoke consent
              </button>
            </>
          ) : (
            <>
              <p className="intel-sub">
                Entering a key isn’t consent. Cloud mode is configured but{" "}
                <strong>nothing is sent</strong> until you explicitly opt in here.
              </p>
              <label className="field field-check">
                <input
                  type="checkbox"
                  checked={consentChecked}
                  onChange={(e) => setConsentChecked(e.target.checked)}
                />
                <span>
                  I understand that redacted, derived findings will be sent to my chosen cloud
                  provider. Raw health records never leave.
                </span>
              </label>
              <button
                type="button"
                className="btn"
                disabled={pending || !consentChecked}
                onClick={() => toggleConsent(true)}
              >
                Grant consent
              </button>
            </>
          )}
        </section>
      )}

      {mode === "cloud" && !savedCloud && (
        <div className="intel-note">Save your cloud provider above, then grant consent here.</div>
      )}

      {saveMsg && (
        <div className={`intel-save ${saveMsg.ok ? "ok" : "bad"}`}>{saveMsg.text}</div>
      )}
    </div>
  );
}

function updateFallback(
  setter: React.Dispatch<React.SetStateAction<FallbackDraft[]>>,
  index: number,
  patch: Partial<FallbackDraft>,
) {
  setter((prev) => prev.map((f, i) => (i === index ? { ...f, ...patch } : f)));
}

function leavesCopy(mode: IntelMode, redact: boolean): string {
  if (mode === "off")
    return "Nothing. With the narrator off, findings are computed on-device and no prompt is ever assembled.";
  if (mode === "local")
    return "Nothing. A local model runs on your own host, so prompts and findings stay inside the trust boundary.";
  return redact
    ? "Only an assembled prompt of derived findings — with identifiers (emails, names, IDs) scrubbed first — is sent to your provider once you consent."
    : "An assembled prompt of derived findings is sent to your provider once you consent. Redaction is OFF, so identifiers are not scrubbed.";
}
