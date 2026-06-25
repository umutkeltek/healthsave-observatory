# Observatory Web vs Grafana

HealthSave Observatory ships two web-visible surfaces in the default stack:

- Observatory web: `http://localhost:4173`
- Grafana: `http://localhost:3000`

They are not competing implementations of the same product. They answer different questions.

## Boundary

| Surface | Use it for | Reads from | Audience |
|---|---|---|---|
| Observatory web | Everyday interpretation, baseline, provenance, findings, sync state | FastAPI v2 read API | Normal users and first-run product UX |
| Grafana | Raw charting, SQL-backed exploration, custom dashboards, debugging | TimescaleDB datasource | Power users, builders, homelab dashboards |

## Observatory Web Logic

Observatory web is the primary product surface. It should explain:

- What changed recently.
- How today compares with the user's own baseline.
- Which sources are contributing data.
- Which findings are evidence-backed.
- Whether the backend is reachable and healthy.
- Empty, no-data, and backend-down states in normal language.

The web app should read through API contracts, not directly from the database. The backend owns normalization, aggregation, provenance, privacy policy, and future auth boundaries.

## Grafana Logic

Grafana is the bundled power-user surface. It should expose data flexibly:

- SQL-backed dashboards.
- Raw metric exploration.
- Prometheus/service health panels.
- Community dashboard examples.
- Debug views for builders and operators.

Grafana may query TimescaleDB directly because that is its job. It intentionally sits closer to the storage layer than Observatory web.

## Why Both Ship

Observatory web is the product direction: a friendly, insight-first surface for everyday use.

Grafana remains valuable because many self-hosters want health data inside their existing dashboard workflow. Keeping Grafana bundled preserves that builder path without forcing every normal user into a chart editor.

## Security

Both surfaces can reveal private health data.

- API publishes on port `8000`.
- Observatory web binds `127.0.0.1:4173` by default through `WEB_BIND`.
- Grafana binds `127.0.0.1:3000` by default through `GRAFANA_BIND`.
- Keep them on a trusted network by default.
- Do not expose either surface over plain HTTP to the internet.
- Put remote access behind HTTPS and deliberate auth.

## Rule Of Thumb

If work changes user experience, baseline explanation, findings, provenance, or first-run clarity, it probably belongs in Observatory web.

If work changes raw charting, custom SQL panels, service dashboards, or builder debugging, it probably belongs in Grafana.
