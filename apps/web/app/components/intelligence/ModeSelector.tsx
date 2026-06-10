"use client";

import type { IntelMode } from "../../lib/api";
import { MODE_CARDS } from "./constants";

export function ModeSelector({
  mode,
  onSelect,
}: {
  mode: IntelMode;
  onSelect: (mode: IntelMode) => void;
}) {
  return (
    <section className="intel-card">
      <h3 className="intel-h">Mode</h3>
      <div className="mode-grid">
        {MODE_CARDS.map((card) => (
          <button
            key={card.id}
            type="button"
            className={`mode-card ${mode === card.id ? "sel" : ""}`}
            onClick={() => onSelect(card.id)}
            aria-pressed={mode === card.id}
          >
            <span className="mode-card-title">{card.title}</span>
            <span className="mode-card-blurb">{card.blurb}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
