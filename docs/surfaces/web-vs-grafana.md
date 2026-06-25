# Observatory Web vs Grafana

HealthSave Observatory ships two web-visible surfaces in the default stack:

- **Observatory web** on `http://localhost:4173`
- **Grafana** on `http://localhost:3000`

They are not competing implementations of the same thing. They answer different questions.

## Separation

| Surface | Use It For | Reads From | Audience |
|---|---|---|---|
| Observatory web | Everyday interpretation: what changed, baseline, provenance, findings | FastAPI v2 read API | Normal users, first-run experience, product UX |
| Grafana | Raw charting, SQL-backed exploration, custom dashboards | TimescaleDB datasource | Power users, builders, debugging, homelab dashboards |

## Observatory Web Logic

Observatory web is the primary product surface. It should lead with meaning:

- today vs personal baseline
- what changed recently
- source coverage and provenance
- findings and briefing cards
- privacy and trust-boundary state
- empty/no-data/backend-down states that are understandable

The web app should prefer API contracts over direct database access. It reads through the v2 API so the backend can keep ownership of data normalization, aggregation, privacy policy, and future auth boundaries.

## Grafana Logic

Grafana is the bundled power-user surface. It should expose data honestly and flexibly:

- SQL-backed dashboards
- raw metric exploration
- Prometheus/service health panels
- custom panels for self-hosters
- useful debugging and community dashboard examples

Grafana may query TimescaleDB directly because that is its job. It is intentionally closer to the storage layer than Observatory web.

## Why Both Ship

Observatory web is the product direction: a friendly, insight-first surface for everyday use.

Grafana is still valuable because the first HealthSave self-hosted pull came from people who wanted their health data in their own dashboards. Keeping Grafana bundled preserves that builder pathway without forcing every normal user into a chart editor.

## Security Posture

Both surfaces can reveal private health data.

- API publishes on port `8000`.
- Observatory web binds `127.0.0.1:4173` by default through `WEB_BIND`.
- Grafana binds `127.0.0.1:3000` by default through `GRAFANA_BIND`.

Only set `WEB_BIND=0.0.0.0` or `GRAFANA_BIND=0.0.0.0` when you deliberately want LAN access. Do not expose either surface directly to the internet over plain HTTP.

## Rule Of Thumb

If the work changes the user experience, baseline explanation, findings, or provenance, it probably belongs in Observatory web.

If the work changes raw charting, custom SQL panels, or builder dashboards, it probably belongs in Grafana.
