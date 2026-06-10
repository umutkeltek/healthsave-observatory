"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { applyIntelligenceAction, consentAction, detectLocalAction } from "../../lib/actions";
import type {
  ApplyIntelligencePayload,
  ConnectionInputPayload,
  IntelligenceView,
  IntelMode,
} from "../../lib/api";
import { CLOUD_PROVIDERS, type FallbackDraft, OLLAMA_DEFAULT_BASE } from "./constants";

export type StatusMsg = { ok: boolean; text: string };

// All form state + the save / detect / consent flows for the Intelligence
// settings page. One useTransition spans every action on purpose: the
// original monolith disabled all buttons together while anything ran, and
// the split must not change that.
export function useIntelligenceForm(view: IntelligenceView) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const [mode, setMode] = useState<IntelMode>(view.mode);
  const [provider, setProvider] = useState(
    view.primary?.provider ?? (view.mode === "local" ? "ollama" : "deepseek"),
  );
  const [model, setModel] = useState(view.primary?.model ?? CLOUD_PROVIDERS[0].model);
  const [baseUrl, setBaseUrl] = useState(view.primary?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [redact, setRedact] = useState(view.redact_cloud_prompts);
  const [fallbacks, setFallbacks] = useState<FallbackDraft[]>(
    view.fallback.map((f) => ({ provider: f.provider ?? "openrouter", model: f.model, apiKey: "" })),
  );
  const [advanced, setAdvanced] = useState(false);
  const [temperature, setTemperature] = useState("");
  const [maxTokens, setMaxTokens] = useState("");

  const [saveMsg, setSaveMsg] = useState<StatusMsg | null>(null);
  const [detectMsg, setDetectMsg] = useState<StatusMsg | null>(null);
  const [consentChecked, setConsentChecked] = useState(false);

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

  // The exact connection input the test probe should use for the CURRENT
  // (possibly unsaved) form values.
  function buildConnectionInput(): ConnectionInputPayload {
    return {
      provider: mode === "local" ? "ollama" : provider,
      model: model.trim(),
      base_url: mode === "local" ? baseUrl.trim() || OLLAMA_DEFAULT_BASE : baseUrl.trim() || null,
      api_key: apiKey.trim() || null,
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

  function detect() {
    setDetectMsg(null);
    startTransition(async () => {
      const result = await detectLocalAction();
      if (!result.ok) {
        setDetectMsg({ ok: false, text: result.error ?? "Detection failed." });
        return;
      }
      const found = (result.candidates ?? []).find((c) => c.reachable);
      if (!found) {
        setDetectMsg({
          ok: false,
          text: "No local model found. Run deploy/local-ai/setup-local-ai.sh to install one.",
        });
        return;
      }
      setBaseUrl(found.url);
      if (found.models.length > 0) setModel(found.models[0]);
      setDetectMsg({
        ok: true,
        text: `Found Ollama at ${found.url}${
          found.models.length ? ` · ${found.models.length} model(s)` : " (no models yet — pull one)"
        }.`,
      });
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

  return {
    pending,
    startTransition,
    mode,
    setMode,
    provider,
    pickProvider,
    model,
    setModel,
    baseUrl,
    setBaseUrl,
    apiKey,
    setApiKey,
    redact,
    setRedact,
    fallbacks,
    setFallbacks,
    advanced,
    setAdvanced,
    temperature,
    setTemperature,
    maxTokens,
    setMaxTokens,
    saveMsg,
    detectMsg,
    consentChecked,
    setConsentChecked,
    buildConnectionInput,
    save,
    detect,
    toggleConsent,
  };
}

export type IntelligenceForm = ReturnType<typeof useIntelligenceForm>;
