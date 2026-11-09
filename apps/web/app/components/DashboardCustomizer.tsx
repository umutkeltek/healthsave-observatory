"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { applyTemplateAction, resetSectionsAction, toggleSectionAction } from "../lib/actions";
import { runAction } from "../lib/session";
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
  const [pending, startTransition] = useTransition();
  const sheetRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState<string | null>(null);
  const active = findTemplate(sections);

  const close = useCallback(() => {
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);

  // Focus trap: first focusable element on open, close on Escape, trap Tab
  useEffect(() => {
    if (!open || !sheetRef.current) return;
    const sheet = sheetRef.current;
    const focusables = sheet.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    first?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        return;
      }
      if (e.key === "Tab") {
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last?.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first?.focus();
          }
        }
      }
    };

    sheet.addEventListener("keydown", onKeyDown);
    return () => sheet.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  const applyTemplate = (id: string) => {
    setError(null);
    startTransition(async () => {
      const result = await runAction(() => applyTemplateAction(id as Template["id"]));
      if (!result.ok) setError(result.error ?? "Could not apply this template.");
      else router.refresh();
    });
  };

  const toggleSection = (key: keyof DashboardSections) => {
    setError(null);
    startTransition(async () => {
      const result = await runAction(() => toggleSectionAction(key));
      if (!result.ok) setError(result.error ?? "Could not update this section.");
      else router.refresh();
    });
  };

  const reset = () => {
    setError(null);
    startTransition(async () => {
      const result = await runAction(() => resetSectionsAction());
      if (!result.ok) setError(result.error ?? "Could not reset the dashboard.");
      else router.refresh();
    });
  };

  if (!open) {
    return (
      <div className="dashboard-customizer-bar">
        <button
          type="button"
          className="btn dashboard-customize-btn"
          ref={triggerRef}
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
        onClick={close}
      />

      <div className="dashboard-sheet" role="dialog" aria-modal="true" aria-label="Customize dashboard" ref={sheetRef}>
        <header className="dashboard-sheet-head">
          <h2>Customize dashboard</h2>
          <button
            type="button"
            className="palette-btn"
            aria-label="Close"
            onClick={close}
          >
            ✕
          </button>
        </header>

        <p className="dashboard-sheet-desc">
          Pick a starting template, then toggle individual sections. Your layout is saved
          automatically — it persists across sessions.
        </p>

        <CustomizerControls
          sections={sections}
          activeId={active?.id ?? null}
          pending={pending}
          error={error}
          onTemplate={applyTemplate}
          onToggle={toggleSection}
          onReset={reset}
        />

        <button
          type="button"
          className="btn dashboard-apply-btn"
          onClick={close}
        >
          Done
        </button>
      </div>
    </>
  );
}

// The sheet's writing controls. While a save is in flight (`pending`) every one
// of them is disabled: each save reads the dashboard cookie and writes it
// back, so a second click before the first lands would overwrite it.
export function CustomizerControls({
  sections,
  activeId,
  pending,
  error,
  onTemplate,
  onToggle,
  onReset,
}: {
  sections: DashboardSections;
  activeId: string | null;
  pending: boolean;
  error: string | null;
  onTemplate: (id: string) => void;
  onToggle: (key: keyof DashboardSections) => void;
  onReset: () => void;
}) {
  return (
    <div aria-busy={pending}>
      {/* Template picker */}
      <div className="template-grid">
        {TEMPLATES.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`template-card ${activeId === t.id ? "template-active" : ""}`}
            onClick={() => onTemplate(t.id)}
            aria-pressed={activeId === t.id}
            disabled={pending}
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
              onChange={() => onToggle(key)}
              disabled={pending || key === "hero"}
            />
            <span className="section-toggle-label">
              <strong>{SECTION_LABELS[key]}</strong>
              {key === "hero" && <em>Always visible</em>}
            </span>
          </label>
        ))}
      </div>

      {error && (
        <p className="exp-error" role="status">
          {error}
        </p>
      )}

      {/* Reset */}
      <button type="button" className="btn dashboard-reset-btn" onClick={onReset} disabled={pending}>
        Reset to full layout
      </button>
    </div>
  );
}
