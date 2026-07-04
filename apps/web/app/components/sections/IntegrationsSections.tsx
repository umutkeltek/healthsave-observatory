// Integrations page section: live source/destination posture from v2 reads.
import Link from "next/link";

import { isNarratorOff } from "../../lib/api";
import { agoLabel, safePrivacy, safeReadiness, safeSources } from "../../lib/load";
import { friendlyName } from "../../lib/provenance";

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

export async function IntegrationsSection() {
  const [sources, readiness, privacy] = await Promise.all([
    safeSources(),
    safeReadiness(),
    safePrivacy(),
  ]);
  const ingestBySource = new Map((readiness?.sources ?? []).map((s) => [s.source_plugin_id ?? "", s]));

  const connected: IntegrationCard[] = (sources ?? []).map((source) => {
    const known = KNOWN_SOURCES[source.plugin_id];
    const ingest = ingestBySource.get(source.plugin_id);
    return {
      key: source.plugin_id,
      name: known?.name ?? friendlyName(source.display_name ?? source.plugin_id),
      kind: known?.kind ?? "source",
      state: "connected",
      detail: ingest
        ? `${ingest.observation_count.toLocaleString()} observations received.`
        : "Source identity exists; no readiness aggregate yet.",
      meta: `last seen ${agoLabel(source.last_seen_at)}`,
    };
  });

  const narratorOff = !privacy || isNarratorOff(privacy.provider);
  const routes: IntegrationCard[] = [
    {
      key: "narrator",
      name: "Narrator",
      kind: "destination · briefs",
      state: "narrator",
      detail: narratorOff
        ? "Off. Findings remain computed evidence only."
        : `${privacy.provider} (${privacy.is_local ? "local" : "cloud"}). Cloud egress ${
            privacy.cloud_active ? "active" : "blocked"
          }.`,
      href: "/intelligence",
      hrefLabel: "Manage",
    },
    {
      key: "ha-mqtt",
      name: "Home Assistant",
      kind: "destination · MQTT",
      state: "host",
      detail: "Publishes canonical streams to your broker from the host bridge.",
      meta: "configured in compose",
    },
    {
      key: "grafana",
      name: "Grafana",
      kind: "destination · dashboards",
      state: "host",
      detail: "Optional power-user dashboards over the same canonical store.",
      meta: "bundled service · port 3300",
    },
    {
      key: "export",
      name: "CSV and JSON",
      kind: "destination · export",
      state: "connected",
      detail: "Export every metric through /api/v2/export. Your data remains portable.",
    },
  ];

  const availableAll: IntegrationCard[] = [
    {
      key: "health-connect",
      name: "Android Health Connect",
      kind: "source · Android app",
      state: "available",
      detail: "In development. Same HealthSave wire contract as iOS.",
    },
    {
      key: "webhook",
      name: "Generic webhook",
      kind: "source · custom ingest",
      state: "available",
      detail: "Planned ingest for scales, cuffs, CSV imports, and scripts.",
    },
  ];
  const available = availableAll.filter((card) => !connected.some((c) => c.key === card.key));

  return (
    <>
      <div className="section-label">Sources, data in</div>
      <section className="grid intg-grid">
        {connected.length === 0 && (
          <article className="card">
            <h2>No sources yet</h2>
            <p className="empty">
              {sources === null
                ? "Backend unreachable. Source state is unknown."
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

      <div className="section-label">Destinations, data out</div>
      <section className="grid intg-grid">
        {routes.map((card) => (
          <IntegrationTile key={card.key} card={card} />
        ))}
      </section>

      <section className="lead">
        <p className="meta">
          Per-device provenance lives in <Link href="/sources">Sources</Link>. Egress policy lives in{" "}
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
