import type { Metadata } from "next";
import Link from "next/link";

import { isNarratorOff } from "../lib/api";
import { agoLabel, safePrivacy, safeReadiness, safeSources } from "../lib/load";
import { friendlyName } from "../lib/provenance";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Integrations · HealthSave Observatory" };

// The integrations home: every way data enters or leaves this host, with its
// REAL live state (from /v2/sources + readiness), honestly split into
// connected / available / on-host-configured. Management depth varies by
// integration — each card says what is actually manageable today.

type CardState = "connected" | "available" | "host" | "narrator";

type IntegrationCard = {
  key: string;
  name: string;
  kind: string;
  state: CardState;
  detail: string;
  meta?: string;
  href?: string;
  hrefLabel?: string;
};

const KNOWN_SOURCES: Record<string, { name: string; kind: string }> = {
  apple_health: { name: "Apple Health", kind: "source · iOS app" },
  "apple-healthkit-ios": { name: "Apple Health", kind: "source · iOS app" },
  whoop: { name: "Whoop", kind: "source · cloud API" },
  amazfit: { name: "Amazfit / Zepp", kind: "source · cloud API" },
};

export default async function IntegrationsPage() {
  const [sources, readiness, privacy] = await Promise.all([
    safeSources(),
    safeReadiness(),
    safePrivacy(),
  ]);

  const ingestBySource = new Map(
    (readiness?.sources ?? []).map((s) => [s.source_plugin_id ?? "", s]),
  );

  const connected: IntegrationCard[] = (sources ?? []).map((source) => {
    const known = KNOWN_SOURCES[source.plugin_id];
    const ingest = ingestBySource.get(source.plugin_id);
    return {
      key: source.plugin_id,
      name: known?.name ?? friendlyName(source.display_name ?? source.plugin_id),
      kind: known?.kind ?? "source",
      state: "connected" as const,
      detail: ingest
        ? `${ingest.observation_count.toLocaleString()} observations · last ingest ${agoLabel(ingest.last_ingested_at)}`
        : `last seen ${agoLabel(source.last_seen_at as unknown as string)}`,
      meta: `since ${new Date(source.first_seen_at as unknown as string).toLocaleDateString()}`,
    };
  });

  const narratorOff = isNarratorOff(privacy?.provider);
  const routes: IntegrationCard[] = [
    {
      key: "narrator",
      name: "LLM Narrator",
      kind: "destination · narration",
      state: "narrator",
      detail: narratorOff
        ? "Off — findings stay numbers-only."
        : `${privacy?.provider ?? "—"} (${privacy?.is_local ? "local" : "cloud"}) · cloud egress ${privacy?.cloud_active ? "active" : "blocked"}`,
      href: "/intelligence",
      hrefLabel: "Manage",
    },
    {
      key: "ha-mqtt",
      name: "Home Assistant · MQTT",
      kind: "destination · near-real-time",
      state: "host",
      detail:
        "Bridge runs on the host (compose profile home-assistant) and publishes canonical streams to your broker.",
      meta: "configured in docker-compose, not from this UI yet",
    },
    {
      key: "grafana",
      name: "Grafana",
      kind: "destination · power dashboards",
      state: "host",
      detail: "Auto-provisioned dashboards over the same store — the optional power-user view.",
      meta: "bundled service · port 3300",
    },
    {
      key: "export",
      name: "CSV / JSON export",
      kind: "destination · take your data",
      state: "connected",
      detail: "Every metric exportable via /api/v2/export — your data is never locked in.",
    },
  ];

  const availableAll: IntegrationCard[] = [
    {
      key: "health-connect",
      name: "Android Health Connect",
      kind: "source · Android app",
      state: "available",
      detail: "The HealthSave Android app is in development — same wire contract as iOS.",
    },
    {
      key: "webhook",
      name: "Generic webhook",
      kind: "source · anything else",
      state: "available",
      detail: "Planned universal ingest for scales, BP cuffs, CSV imports and custom scripts.",
    },
  ];
  const available = availableAll.filter((card) => !connected.some((c) => c.key === card.key));

  return (
    <>
      <section className="lead">
        <p className="lib-intro">
          Everything that feeds this Observatory or receives from it — with live state. Sources
          push data in; destinations are where your data goes <em>only</em> when you route it.
        </p>
      </section>

      <div className="section-label">Sources — data in</div>
      <section className="grid">
        {connected.length === 0 && (
          <article className="card">
            <h2>No sources yet</h2>
            <p className="empty">
              {sources === null
                ? "Backend unreachable — source state unknown."
                : "Point the HealthSave app at this server to connect your first source."}
            </p>
          </article>
        )}
        {connected.map((card) => (
          <IntegrationTile key={card.key} card={card} />
        ))}
        {available.map((card) => (
          <IntegrationTile key={card.key} card={card} />
        ))}
      </section>

      <div className="section-label">Destinations — data out (your call)</div>
      <section className="grid">
        {routes.map((card) => (
          <IntegrationTile key={card.key} card={card} />
        ))}
      </section>

      <section className="lead">
        <p className="meta">
          Deeper provenance lives in <Link href="/sources">Sources</Link> (per-device streams) —
          and nothing leaves this host without the policy you can inspect under{" "}
          <Link href="/privacy">Privacy</Link>.
        </p>
      </section>
    </>
  );
}

function IntegrationTile({ card }: { card: IntegrationCard }) {
  const badge =
    card.state === "connected"
      ? { label: "connected", cls: "intg-on" }
      : card.state === "narrator"
        ? { label: "manageable", cls: "intg-manage" }
        : card.state === "host"
          ? { label: "on host", cls: "intg-host" }
          : { label: "coming", cls: "intg-soon" };
  return (
    <article className="card intg-card">
      <div className="intg-head">
        <h2>{card.name}</h2>
        <span className={`intg-badge ${badge.cls}`}>{badge.label}</span>
      </div>
      <div className="intg-kind mono">{card.kind}</div>
      <p className="intg-detail">{card.detail}</p>
      {card.meta && <div className="meta">{card.meta}</div>}
      {card.href && (
        <div className="exp-action">
          <Link className="btn btn-ghost" href={card.href}>
            {card.hrefLabel ?? "Open"}
          </Link>
        </div>
      )}
    </article>
  );
}
