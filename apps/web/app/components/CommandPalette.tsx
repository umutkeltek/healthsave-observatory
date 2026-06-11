"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

// ⌘K palette: jump to any page or any of the ~190 catalog signals without
// hunting the nav or the Library grid. Pure client island — the metric list
// arrives server-rendered via PaletteHost, queries never leave the page.

export type PaletteMetric = { id: string; name: string; category: string };

const PAGES: { label: string; href: string }[] = [
  { label: "Today", href: "/" },
  { label: "Experiments", href: "/experiments" },
  { label: "Findings", href: "/findings" },
  { label: "Sources", href: "/sources" },
  { label: "Data", href: "/data" },
  { label: "Library", href: "/library" },
  { label: "Compare", href: "/compare" },
  { label: "Relationships", href: "/relationships" },
  { label: "Integrations", href: "/integrations" },
  { label: "Privacy", href: "/privacy" },
  { label: "Intelligence", href: "/intelligence" },
  { label: "Settings", href: "/settings" },
];

type Item = { key: string; label: string; hint: string; href: string };

// Rank: prefix match > word-boundary match > substring; pages above signals
// at equal rank so "in" finds Intelligence before a dozen metrics.
function score(haystack: string, q: string): number {
  const h = haystack.toLowerCase();
  if (h.startsWith(q)) return 3;
  if (h.includes(` ${q}`) || h.includes(`.${q}`) || h.includes(`_${q}`)) return 2;
  if (h.includes(q)) return 1;
  return 0;
}

const MAX_RESULTS = 12;

export function CommandPalette({ metrics }: { metrics: PaletteMetric[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        setQ("");
        setActive(0);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const onOpen = () => {
      setOpen(true);
      setQ("");
      setActive(0);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("hs:palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("hs:palette", onOpen);
    };
  }, []);

  const items = useMemo<Item[]>(() => {
    const query = q.trim().toLowerCase();
    const pages: Item[] = PAGES.map((p) => ({
      key: p.href,
      label: p.label,
      hint: "page",
      href: p.href,
    }));
    const signals: Item[] = metrics.map((m) => ({
      key: m.id,
      label: m.name,
      hint: m.category || "signal",
      href: `/library/${encodeURIComponent(m.id)}`,
    }));
    if (!query) return pages.slice(0, MAX_RESULTS);
    const ranked = (list: Item[], idHaystack: (i: Item) => string) =>
      list
        .map((item) => ({ item, s: Math.max(score(item.label, query), score(idHaystack(item), query)) }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s);
    return [...ranked(pages, (i) => i.href), ...ranked(signals, (i) => i.key)]
      .slice(0, MAX_RESULTS)
      .map((x) => x.item);
  }, [metrics, q]);

  useEffect(() => {
    setActive(0);
  }, [q]);

  useEffect(() => {
    listRef.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const go = (href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  };

  const onInputKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && items[active]) {
      e.preventDefault();
      go(items[active].href);
    }
  };

  return (
    <div
      className="palette-scrim"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Jump to a signal or page">
        <input
          className="palette-input"
          // eslint-disable-next-line jsx-a11y/no-autofocus -- a freshly opened palette IS the focus target
          autoFocus
          value={q}
          placeholder="Jump to a signal or page…"
          aria-label="Search signals and pages"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-results"
          aria-activedescendant={items[active] ? `palette-opt-${items[active].key}` : undefined}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onInputKey}
        />
        {items.length === 0 ? (
          <p className="palette-empty">Nothing matches “{q}”.</p>
        ) : (
          <ul className="palette-list" id="palette-results" role="listbox" ref={listRef}>
            {items.map((item, i) => (
              <li
                key={item.key}
                id={`palette-opt-${item.key}`}
                className={`palette-item ${i === active ? "active" : ""}`}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep input focus until navigation
                  go(item.href);
                }}
              >
                <span>{item.label}</span>
                <span className="palette-hint">{item.hint}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
