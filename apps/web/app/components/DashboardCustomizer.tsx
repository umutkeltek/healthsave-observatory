"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { applyTemplateAction, resetSectionsAction, toggleSectionAction } from "../lib/actions";
import type { DashboardSections, Template } from "../lib/templates";
import { TEMPLATES } from "../lib/templates";

const SECTION_LABELS: Record<keyof DashboardSections, string> = {
  hero: "Recovery hero",
  goal: "Focus goal",
  story: "Weekly brief & findings",
  signals: "Signal cards",
  vault: "Data privacy card",
  readiness: "Data readiness",
  savedPanels: "Saved Explore panels",
};

function findTemplate(sections: DashboardSections): Template | null {
  return TEMPLATES.find((t) =>
    (Object.keys(t.sections) as (keyof DashboardSections)[]).every(
      (k) => t.sections[k] === sections[k],
    ),
  ) ?? null;
}

export function DashboardCustomizer({ sections }: { sections: DashboardSections }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [, startTransition] = useTransition();
  const active = findTemplate(sections);

  const applyTemplate = (id: string) => {
    startTransition(async () => {
      await applyTemplateAction(id as Template["id"]);
      router.refresh();
    });
  };

  const toggleSection = (key: keyof DashboardSections) => {
    startTransition(async () => {
      await toggleSectionAction(key);
      router.refresh();
    });
  };

  const reset = () => {
    startTransition(async () => {
      await resetSectionsAction();
      router.refresh();
    });
  };

  if (!open) {
    return (
      <div className="dashboard-customizer-bar">
        <button
          type="button"
          className="btn dashboard-customize-btn"
          onClick={() => setOpen(true)}
        >
          {active ? `${active.icon} ${active.label}` : "◆ Customize"}
        </button>
        <span className="dashboard-customizer-hint">Tap to pick a view or toggle sections.</span>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        className="nav-scrim dashboard-scrim"
        aria-label="Close dashboard customizer"
        onClick={() => setOpen(false)}
      />

      <div className="dashboard-sheet" role="dialog" aria-label="Customize dashboard">
        <header className="dashboard-sheet-head">
          <h2>Customize dashboard</h2>
          <button
            type="button"
            className="palette-btn"
            aria-label="Close"
            onClick={() => setOpen(false)}
          >
            ✕
          </button>
        </header>

        <p className="dashboard-sheet-desc">
          Pick a starting template, then toggle individual sections. Your layout is saved
          automatically — it persists across sessions.
        </p>

        {/* Template picker */}
        <div className="template-grid">
          {TEMPLATES.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`template-card ${active?.id === t.id ? "template-active" : ""}`}
              onClick={() => applyTemplate(t.id)}
            >
              <span className="template-icon">{t.icon}</span>
              <strong>{t.label}</strong>
              <span className="template-short">{t.short}</span>
            </button>
          ))}
        </div>

        {/* Section toggles */}
        <div className="dashboard-section-toggles">
          <h3>Section visibility</h3>
          {(Object.keys(sections) as (keyof DashboardSections)[]).map((key) => (
            <label key={key} className="section-toggle-row">
              <input
                type="checkbox"
                checked={sections[key]}
                onChange={() => toggleSection(key)}
                disabled={key === "hero"}
              />
              <span className="section-toggle-label">
                <strong>{SECTION_LABELS[key]}</strong>
                {key === "hero" && <em>Always visible</em>}
              </span>
            </label>
          ))}
        </div>

        {/* Reset */}
        <button type="button" className="btn dashboard-reset-btn" onClick={reset}>
          Reset to full layout
        </button>

        <button
          type="button"
          className="btn dashboard-apply-btn"
          onClick={() => setOpen(false)}
        >
          Done
        </button>
      </div>
    </>
  );
}
