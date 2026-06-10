"use client";

import { useMemo } from "react";

import type { IntelligenceView } from "../lib/api";
import { ConsentPanel } from "./intelligence/ConsentPanel";
import { leavesCopy } from "./intelligence/constants";
import { FallbackChainEditor } from "./intelligence/FallbackChainEditor";
import { ModeSelector } from "./intelligence/ModeSelector";
import { ProviderConfig } from "./intelligence/ProviderConfig";
import { useConnectionTest } from "./intelligence/useConnectionTest";
import { useIntelligenceForm } from "./intelligence/useIntelligenceForm";

// The Intelligence settings page, assembled from components/intelligence/*.
// State lives in useIntelligenceForm (one shared transition so every action
// disables every button); the test probe rides the same transition via
// useConnectionTest. This file only composes.
export function IntelligenceSettings({ initial }: { initial: IntelligenceView | null }) {
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

  const form = useIntelligenceForm(view);
  const test = useConnectionTest(form.startTransition);

  const savedCloud = view.mode === "cloud" && view.primary !== null;
  const whatLeaves = useMemo(() => leavesCopy(form.mode, form.redact), [form.mode, form.redact]);

  return (
    <div className="intel">
      {view.managed_by_env && (
        <div className="intel-banner">
          <strong>Managed by environment.</strong> The narrator is currently running from
          deploy-time configuration{view.env_provider ? ` (${view.env_provider})` : ""}. Saving
          here writes to the database and takes over — your edits become the source of truth.
        </div>
      )}

      <ModeSelector mode={form.mode} onSelect={form.setMode} />

      {form.mode !== "off" && <ProviderConfig form={form} test={test} view={view} />}

      {form.mode === "cloud" && <FallbackChainEditor form={form} />}

      <section className="intel-card intel-leaves">
        <h3 className="intel-h">What leaves your host</h3>
        <p className="brief-body">{whatLeaves}</p>
        <div className="assurance">Raw observations never leave the host — in any mode.</div>
      </section>

      {savedCloud && <ConsentPanel form={form} view={view} />}

      {form.mode === "cloud" && !savedCloud && (
        <div className="intel-note">Save your cloud provider above, then grant consent here.</div>
      )}

      {form.saveMsg && (
        <div className={`intel-save ${form.saveMsg.ok ? "ok" : "bad"}`}>{form.saveMsg.text}</div>
      )}
    </div>
  );
}
