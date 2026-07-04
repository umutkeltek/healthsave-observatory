"use client";

import { useMemo } from "react";

import {
  isNarratorOff,
  type IntelligenceView,
  type IntelMode,
  type Privacy,
} from "../lib/api";
import { ConsentPanel } from "./intelligence/ConsentPanel";
import { leavesCopy } from "./intelligence/constants";
import { FallbackChainEditor } from "./intelligence/FallbackChainEditor";
import { ModeSelector } from "./intelligence/ModeSelector";
import { ProviderConfig } from "./intelligence/ProviderConfig";
import { useConnectionTest } from "./intelligence/useConnectionTest";
import { useIntelligenceForm } from "./intelligence/useIntelligenceForm";

const EMPTY_VIEW: IntelligenceView = {
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

function effectiveMode(view: IntelligenceView, privacy: Privacy | null): IntelMode {
  if (privacy) {
    if (isNarratorOff(privacy.provider)) return "off";
    if (privacy.is_local) return "local";
    return "cloud";
  }

  if (view.managed_by_env && view.env_provider && !isNarratorOff(view.env_provider)) {
    return view.env_provider.toLowerCase() === "ollama" ? "local" : "cloud";
  }

  return view.mode;
}

function runtimeLabel(mode: IntelMode, privacy: Privacy | null): string {
  if (mode === "off") return "Narration off";
  if (mode === "local") return `Local narration${privacy?.provider ? ` · ${privacy.provider}` : ""}`;
  if (privacy?.cloud_active) return `Cloud narration active · ${privacy.provider}`;
  return `Cloud provider configured${privacy?.provider ? ` · ${privacy.provider}` : ""}`;
}

function runtimeDetail(
  mode: IntelMode,
  view: IntelligenceView,
  privacy: Privacy | null,
): string {
  const source = view.managed_by_env
    ? "Running from deploy-time environment. Saving below creates a database override and becomes the source of truth."
    : "Running from saved Intelligence settings.";

  if (mode === "cloud" && privacy && !privacy.cloud_active) {
    return `${source} Cloud egress is currently blocked until consent and policy allow it.`;
  }

  return source;
}

// Intelligence settings page, assembled from components/intelligence/*.
// The form edits the saved database override. When deploy-time env config is
// currently effective, initialize the editable mode from the runtime posture so
// the selected card does not contradict the shell/privacy chips.
export function IntelligenceSettings({
  initial,
  privacy,
}: {
  initial: IntelligenceView | null;
  privacy: Privacy | null;
}) {
  const view = initial ?? EMPTY_VIEW;
  const runtimeMode = effectiveMode(view, privacy);
  const editableView =
    view.managed_by_env && view.mode === "off" && runtimeMode !== "off"
      ? { ...view, mode: runtimeMode }
      : view;

  const form = useIntelligenceForm(editableView);
  const test = useConnectionTest(form.startTransition);
  const savedCloud = editableView.mode === "cloud" && editableView.primary !== null;
  const whatLeaves = useMemo(() => leavesCopy(form.mode, form.redact), [form.mode, form.redact]);
  const runtimeTone = runtimeMode === "cloud" && privacy?.cloud_active ? "waiting" : "ready";

  return (
    <div className="intel">
      <section className="intel-card intel-runtime">
        <div>
          <h3 className="intel-h">Current runtime</h3>
          <p className="brief-body">{runtimeLabel(runtimeMode, privacy)}</p>
          <p className="intel-muted">{runtimeDetail(runtimeMode, view, privacy)}</p>
        </div>
        <span className={`badge ${runtimeTone}`}>
          {view.managed_by_env ? "env managed" : `rev ${view.revision}`}
        </span>
      </section>

      <ModeSelector mode={form.mode} onSelect={form.setMode} />

      {form.mode !== "off" && <ProviderConfig form={form} test={test} view={editableView} />}

      {form.mode === "cloud" && <FallbackChainEditor form={form} />}

      <section className="intel-card intel-leaves">
        <h3 className="intel-h">What would leave host</h3>
        <p className="brief-body">{whatLeaves}</p>
        <div className="assurance">Raw observations never leave host in any mode.</div>
      </section>

      {savedCloud && <ConsentPanel form={form} view={editableView} />}

      {form.mode === "cloud" && !savedCloud && (
        <div className="intel-note">
          {view.managed_by_env
            ? "Save a cloud provider to take over from the deploy environment. Database consent appears after that."
            : "Save your cloud provider above, then grant consent here."}
        </div>
      )}

      {form.saveMsg && (
        <div className={`intel-save ${form.saveMsg.ok ? "ok" : "bad"}`}>
          {form.saveMsg.text}
        </div>
      )}
    </div>
  );
}
