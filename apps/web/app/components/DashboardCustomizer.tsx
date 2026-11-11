"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, useTransition } from "react";
import { createPortal } from "react-dom";

import { applyTemplateAction, resetSectionsAction, toggleSectionAction } from "../lib/actions";
import { runAction } from "../lib/session";
import type { DashboardSections, Template } from "../lib/templates";
import { TEMPLATES } from "../lib/templates";
import { WriteGate } from "../lib/writeGate";

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

// One write at a time (lib/writeGate.ts): each one reads the dashboard cookie
// and writes it back. `initiallyOpen` and `gate` are test seams.
export function DashboardCustomizer({
  sections,
  initiallyOpen = false,
  gate: givenGate,
}: {
  sections: DashboardSections;
  initiallyOpen?: boolean;
  gate?: WriteGate;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(initiallyOpen);
  const [gate] = useState(() => givenGate ?? new WriteGate());
  const writing = useSyncExternalStore(gate.subscribe, gate.isBusy, gate.isBusy);
  // A save lands in two steps: the action, then the refreshed server render
  // that carries the new sections. On a slow link the second step takes
  // seconds, and the controls must not look ready while they still show the
  // old state. Busy until new sections arrive (or the sheet closes).
  const [awaitingRender, setAwaitingRender] = useState(false);
  useEffect(() => setAwaitingRender(false), [sections]);
  const pending = writing || awaitingRender;
  // Writes still run inside a transition, so an unexpected failure reaches the
  // error boundary as before (runAction rethrows anything but a signed-out
  // answer) instead of becoming an unhandled rejection.
  const [, startTransition] = useTransition();
  const write = (action: () => Promise<void>) => startTransition(async () => void (await gate.run(action)));
  const sheetRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState<string | null>(null);
  const active = findTemplate(sections);

  const close = useCallback(() => {
    setOpen(false);
    setAwaitingRender(false);
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

  const refresh = () => {
    setAwaitingRender(true);
    router.refresh();
  };

  const applyTemplate = (id: string) => {
    setError(null);
    write(async () => {
      const result = await runAction(() => applyTemplateAction(id as Template["id"]));
      if (!result.ok) setError(result.error ?? "Could not apply this template.");
      else refresh();
    });
  };

  const toggleSection = (key: keyof DashboardSections) => {
    setError(null);
    write(async () => {
      const result = await runAction(() => toggleSectionAction(key));
      if (!result.ok) setError(result.error ?? "Could not update this section.");
      else refresh();
    });
  };

  const reset = () => {
    setError(null);
    write(async () => {
      const result = await runAction(() => resetSectionsAction());
      if (!result.ok) setError(result.error ?? "Could not reset the dashboard.");
      else refresh();
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

  const sheet = (
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
  // Rendered into <body>: inside the page, the sticky top bar stacks above the
  // scrim and stays tappable. The server (and the markup tests) has no
  // document; the sheet only ever opens on the client.
  return typeof document === "undefined" ? sheet : createPortal(sheet, document.body);
}

// The sheet's writing controls. While a save is in flight (`pending`) every one
// of them is unavailable: each save reads the dashboard cookie and writes it
// back. aria-disabled, not disabled: a disabled control drops focus to <body>,
// and with it the sheet's Escape and Tab handling.
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
            onClick={() => {
              if (!pending) onTemplate(t.id);
            }}
            aria-pressed={activeId === t.id}
            aria-disabled={pending}
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
              data-section={key}
              checked={sections[key]}
              onChange={() => {
                if (!pending) onToggle(key);
              }}
              disabled={key === "hero"}
              aria-disabled={pending && key !== "hero" ? true : undefined}
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
      <button
        type="button"
        className="btn dashboard-reset-btn"
        onClick={() => {
          if (!pending) onReset();
        }}
        aria-disabled={pending}
      >
        Reset to full layout
      </button>
    </div>
  );
}
