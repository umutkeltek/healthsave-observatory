import type { Metadata } from "next";
import Link from "next/link";

import { fetchMeta, isNarratorOff } from "../lib/api";
import { PinButton } from "../components/PinButton";
import { StandaloneDensityToggle } from "../components/DensityToggle";
import { safeIntelligence, safeMetrics, safePrivacy, safeSources } from "../lib/load";
import { getDensity, getPinnedMetrics } from "../lib/prefs";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Settings · HealthSave Observatory" };

async function safeMeta() {
  try {
    return await fetchMeta();
  } catch {
    return null;
  }
}

// One place to see and manage everything configurable, end to end. Each
// section either manages inline (view mode, pins) or links to its dedicated
// surface (Intelligence, Integrations) — no orphaned settings.
export default async function SettingsPage() {
  const [density, pinned, catalog, intelligence, privacy, sources, meta] = await Promise.all([
    getDensity(),
    getPinnedMetrics(),
    safeMetrics(),
    safeIntelligence(),
    safePrivacy(),
    safeSources(),
    safeMeta(),
  ]);

  const pinnedRows = pinned.map((id) => ({
    id,
    name: catalog?.find((m) => m.id === id)?.display_name ?? id,
  }));
  const narratorOff = isNarratorOff(privacy?.provider);

  return (
    <>
      <section className="lead">
        <div className="card">
          <h2>View</h2>
          <p className="set-hint">
            <strong>Essentials</strong> keeps the navigation to the daily surfaces;{" "}
            <strong>Observatory</strong> opens every power view. All pages stay reachable by URL in
            both modes.
          </p>
          <div className="set-toggle-row">
            <StandaloneDensityToggle density={density} />
          </div>
        </div>
      </section>

      <section className="lead">
        <div className="card">
          <h2>Pinned signals</h2>
          {pinnedRows.length === 0 ? (
            <p className="empty">
              Nothing pinned — the Today grid shows the curated defaults. Star any signal in the{" "}
              <Link href="/library">Library</Link> to build your own grid.
            </p>
          ) : (
            <ul className="set-pins">
              {pinnedRows.map((row) => (
                <li key={row.id} className="set-pin-row">
                  <PinButton metricId={row.id} pinned />
                  <Link href={`/library/${encodeURIComponent(row.id)}`} className="lib-name">
                    {row.name}
                  </Link>
                  <span className="mono set-pin-id">{row.id}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <div className="row-2">
        <article className="card">
          <h2>Intelligence</h2>
          <p className="set-hint">
            {privacy
              ? `Narrator ${
                  narratorOff
                    ? "off"
                    : `${privacy.is_local ? "local" : "cloud"} · ${privacy.provider}`
                }${intelligence?.managed_by_env ? " (set by deploy env)" : ""} — provider, fallback chain, redaction and consent are managed end-to-end on the Intelligence page.`
              : "Narrator settings unavailable (backend unreachable)."}
          </p>
          <div className="exp-action">
            <Link className="btn btn-ghost" href="/intelligence">
              Manage narrator
            </Link>
          </div>
        </article>

        <article className="card">
          <h2>Integrations</h2>
          <p className="set-hint">
            {sources
              ? `${sources.length} source${sources.length === 1 ? "" : "s"} connected. Sources, destinations and what each one can do live on the Integrations page.`
              : "Source state unavailable (backend unreachable)."}
          </p>
          <div className="exp-action">
            <Link className="btn btn-ghost" href="/integrations">
              Manage integrations
            </Link>
          </div>
        </article>
      </div>

      <section className="lead">
        <div className="card">
          <h2>System</h2>
          {meta ? (
            <div className="set-system mono">
              <span>
                <span className="lib-stat-label">api</span> {meta.versions.api_contract}
              </span>
              <span>
                <span className="lib-stat-label">ontology</span> {meta.versions.ontology}
              </span>
              <span>
                <span className="lib-stat-label">normalizer</span> {meta.versions.normalizer}
              </span>
              <span>
                <span className="lib-stat-label">fusion</span> {meta.versions.fusion_policy}
              </span>
              <span>
                <span className="lib-stat-label">v2</span> {meta.v2_status}
              </span>
            </div>
          ) : (
            <p className="empty">Version info unavailable (backend unreachable).</p>
          )}
          <p className="meta" style={{ marginTop: 10 }}>
            Egress posture and the chain of custody live under <Link href="/privacy">Privacy</Link>.
          </p>
        </div>
      </section>
    </>
  );
}
