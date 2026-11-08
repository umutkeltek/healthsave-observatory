"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { applyIntelligenceAction, consentAction, detectLocalAction } from "../../lib/actions";
import { runAction } from "../../lib/session";
import type {
  ApplyIntelligencePayload,
  ConnectionInputPayload,
  IntelligenceView,
  IntelMode,
} from "../../lib/api";
import type { FallbackDraft } from "./constants";
import {
  connectionInputFor,
  initialDrafts,
  primaryFor,
  type ProviderDrafts,
  withLocalBaseUrl,
  withModel,
  withProvider,
} from "./providerDrafts";

export type StatusMsg = { ok: boolean; text: string };

// All form state + the save / detect / consent flows for the Intelligence
// settings page. One useTransition spans every action on purpose: the
// original monolith disabled all buttons together while anything ran, and
// the split must not change that.
export function useIntelligenceForm(view: IntelligenceView) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const [mode, setMode] = useState<IntelMode>(view.mode);
  // One draft per mode (providerDrafts.ts): only the visible mode's fields
  // are ever sent.
  const [drafts, setDrafts] = useState<ProviderDrafts>(() => initialDrafts(view.primary));
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

  const provider = drafts.cloud.provider;
  const model = mode === "local" ? drafts.local.model : drafts.cloud.model;
  const baseUrl = drafts.local.baseUrl;
  const setModel = (next: string) => setDrafts((d) => withModel(d, mode === "local" ? "local" : "cloud", next));
  const setBaseUrl = (next: string) => setDrafts((d) => withLocalBaseUrl(d, next));

  function pickProvider(id: string) {
    setDrafts((d) => withProvider(d, id, view.primary));
  }

  function buildPayload(): ApplyIntelligencePayload {
    if (mode === "off") return { mode: "off" };
    const primary = primaryFor(mode, drafts, { apiKey, temperature, maxTokens, advanced });

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
    return connectionInputFor(mode === "local" ? "local" : "cloud", drafts, apiKey);
  }

  function save() {
    setSaveMsg(null);
    startTransition(async () => {
      const result = await runAction(() => applyIntelligenceAction(buildPayload()));
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
      const result = await runAction(() => detectLocalAction());
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
      setDrafts((d) => {
        const located = withLocalBaseUrl(d, found.url);
        return found.models.length > 0 ? withModel(located, "local", found.models[0]) : located;
      });
      setDetectMsg({
        ok: true,
        text: `Found Ollama at ${found.url}${
          found.models.length ? ` · ${found.models.length} model(s)` : " (no models yet - pull one)"
        }.`,
      });
    });
  }

  function toggleConsent(grant: boolean) {
    startTransition(async () => {
      const result = await runAction(() =>
        consentAction({
          granted: grant,
          consent_version: grant ? new Date().toISOString().slice(0, 10) : null,
        }),
      );
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
