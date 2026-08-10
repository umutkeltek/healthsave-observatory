// Settings page sections - preferences (cookie reads), the service cards
// (network reads), and the system versions each stream behind their own
// boundary so a slow backend never delays the inline-manageable prefs.

import Link from "next/link";

import { fetchAnalyticalTime, fetchMeta, isNarratorOff } from "../../lib/api";
import { AnalyticalTimeSettingsForm } from "../AnalyticalTimeSettings";
import { LanguageSwitcher } from "../LanguageSwitcher";
import { PinButton } from "../PinButton";
import { StandaloneDensityToggle } from "../DensityToggle";
import { getDictionary } from "../../lib/i18n";
import { getAvailableLocales, getLocale } from "../../lib/i18n.server";
import { safeIntelligence, safeMetrics, safePrivacy, safeSources } from "../../lib/load";
import { getDensity, getPinnedMetrics } from "../../lib/prefs";

async function safeMeta() {
  try {
    return await fetchMeta();
  } catch {
    return null;
  }
}

async function safeAnalyticalTime() {
  try {
    return await fetchAnalyticalTime();
  } catch {
    return null;
  }
}

export async function AnalyticalTimeSection() {
  const settings = await safeAnalyticalTime();
  if (!settings) {
    return (
      <section className="lead">
        <article className="card">
          <h2>Analytical day</h2>
          <p className="empty">Time-basis settings unavailable (backend unreachable).</p>
        </article>
      </section>
    );
  }
  return <section className="lead"><AnalyticalTimeSettingsForm initial={settings} /></section>;
}

export async function PreferencesSection() {
  const [density, pinned, catalog, locale] = await Promise.all([
    getDensity(),
    getPinnedMetrics(),
    safeMetrics(),
    getLocale(),
  ]);
  const dict = getDictionary(locale);
  const availableLocales = getAvailableLocales();
  const pinnedRows = pinned.map((id) => ({
    id,
    name: catalog?.find((m) => m.id === id)?.display_name ?? id,
  }));
  return (
    <>
      <section className="lead">
        <div className="card">
          <h2>{dict.settings.viewTitle}</h2>
          <p className="set-hint">
            <strong>{dict.settings.viewHintEssentials}</strong>{" "}
            {dict.settings.viewHint.split("{observatory}")[0]}
            <strong>{dict.settings.viewHintObservatory}</strong>
            {dict.settings.viewHint.split("{observatory}")[1]}
          </p>
          <div className="set-toggle-row">
            <StandaloneDensityToggle density={density} />
          </div>
        </div>
      </section>

      {availableLocales.length > 1 ? (
        <section className="lead">
          <div className="card">
            <h2>{dict.settings.languageTitle}</h2>
            <p className="set-hint">{dict.settings.languageHint}</p>
            <div className="set-toggle-row">
              <LanguageSwitcher />
            </div>
          </div>
        </section>
      ) : null}

      <section className="lead">
        <div className="card">
          <h2>{dict.settings.pinnedSignals}</h2>
          {pinnedRows.length === 0 ? (
            <p className="empty">
              {dict.settings.noPinned.split("{library}")[0]}
              <Link href="/library">{dict.nav.library}</Link>
              {dict.settings.noPinned.split("{library}")[1]}
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
    </>
  );
}

export async function ServicesSection() {
  const [intelligence, privacy, sources] = await Promise.all([
    safeIntelligence(),
    safePrivacy(),
    safeSources(),
  ]);
  const narratorOff = isNarratorOff(privacy?.provider);
  return (
    <div className="row-2">
      <article className="card">
        <h2>Intelligence</h2>
        <p className="set-hint">
          {privacy
            ? `Narrator ${
                narratorOff
                  ? "off"
                  : `${privacy.is_local ? "local" : "cloud"} · ${privacy.provider}`
              }${intelligence?.managed_by_env ? " (set by deploy env)" : ""} - provider, fallback chain, redaction and consent are managed end-to-end on the Intelligence page.`
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
  );
}

export async function SystemSection() {
  const meta = await safeMeta();
  return (
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
  );
}
