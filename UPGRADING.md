# Upgrading HealthSave Observatory

How to update an existing install safely. The general procedure:

```bash
git pull
docker compose up -d --build        # the `migrate` service applies additive
                                    # schema migrations before `api` starts
```

Migrations are **always additive** (no table is renamed or dropped), and the
`migrate` service runs them automatically on every boot before the API comes up,
so a plain `up -d --build` is the safe upgrade path.

---

## Version notes

### R1 (2026-06) — release-grade core

Three changes. **Only the first can affect an existing install**, and the default
config carries the common path through transparently.

#### 1. Auth is now default-deny (SECURITY-001) — read this if you run without an API key

Previously, if `API_KEY` was empty the API served your health data **open** (with
a startup warning). Now the PHI surface is **default-deny**: with **no `API_KEY`**
and **no `ALLOW_NO_AUTH`**, those routes return **`503 auth_not_configured`**
instead of serving open.

What this means for you:

| How you run it | Effect on upgrade | Action |
|---|---|---|
| `docker compose up` (this repo's compose) | **None.** The compose now defaults `ALLOW_NO_AUTH=true`, so a keyless local stack keeps serving (with a loud warning). | none |
| You set `API_KEY` (setup.sh / remote-vm deploy / your own) | **None.** Key auth is enforced exactly as before. | none |
| `deploy/remote-vm/deploy.sh` | **None.** It already mints/keeps an `API_KEY`. | none |
| Custom orchestration (raw `docker run`, k8s, systemd) with **no key** | The API returns `503` until configured — this is the intended hardening. | Set `API_KEY=<token>` (recommended for anything network-reachable) **or** `ALLOW_NO_AUTH=true` to deliberately keep it open. |

If you see `503 auth_not_configured`, the startup log tells you exactly what to
set. **Recommendation:** set an `API_KEY` for any install reachable beyond
localhost — this backend stores health data.

#### 2. Optional rate-limiting reverse proxy (SECURITY-004)

New, **opt-in** — nothing changes unless you adopt it. For internet-facing
installs, `deploy/reverse-proxy/` adds an nginx gateway with per-IP rate limiting
and TLS, and closes the direct API port. See its README.

#### 3. Internal refactor (ARCH-001) — no action

Shared parsing/mapping helpers moved below the storage layer
(`normalization.*`, `contracts._base`); `server.ingestion.*` keep working via


### R2 (2026-09) — additive v2 ingest wire (Plan 2026-09-03)

Adds the `POST /api/v2/apple/batch` route and the additive `source_uuid` +
`status='superseded'` columns on the v1 dedicated tables (`heart_rate`, `hrv`,
`blood_oxygen`, `body_temperature`, `sleep_sessions`). **No operator action
required for the v1 surface to keep working** — the v2 route is additive at
the URL layer.

#### 1. Migration `025_apple_source_uuid_and_superseded.sql` — auto-applied

Adds nullable `source_uuid UUID` + `status TEXT NOT NULL DEFAULT 'active'`
to the v1 dedicated tables. Partial unique index `WHERE source_uuid IS NOT NULL`
enables `(owner_id, source_uuid, time) WHERE source_uuid IS NOT NULL` upserts
(the dedicated tables are TimescaleDB hypertables, so the partition column
`time` must be in every unique index);
legacy rows keep the existing `(owner_id, device_id, time)` conflict path.
The compose `migrate` service applies it before the API comes up — same
additive-only contract as every prior migration. Existing rows are untouched.

#### 2. New v2 ingest endpoint — no client action required

`POST /api/v2/apple/batch` accepts `schema_version=2` payloads with
`uuid` / `startDate` / `endDate` / `unit` / `tzOffsetMinutes` / `motionContext`
per sample plus a top-level `deletions: [{uuid}]` array. The
response shape is identical to v1. Shipped iOS binaries keep posting to
`/api/apple/batch` unchanged; HealthSave 1.7.0+ defaults to v2 and falls
back to v1 on `404`/`405` (no infinite retry).

#### 3. RHR and other revision-via-delete metrics

HealthKit metrics that revise by delete+reinsert (resting heart rate,
workout summaries) now propagate deletions: the server marks
`canonical_observations` and the v1 dedicated table rows `status='superseded'`
by `source_uuid`. This only applies to v2 batches; v1 batches behave exactly
as before.

#### 4. Self-host dry-run (recommended before flipping 1.7.0 clients to v2)

A developer device running a `HealthSave 1.7.0+` build that has been promoted
to v2 should send a v2 batch against the migrated instance. The minimal
post-deploy check is:

```sql
-- canonical row carries the sample UUID as source_record_uid
SELECT source_record_uid, metric_id, status
FROM canonical_observations
WHERE source_record_uid IS NOT NULL
ORDER BY updated_at DESC
LIMIT 5;

-- v1 dedicated tables have the source_uuid stamped + the active/superseded
-- status split working
SELECT status, COUNT(*) FROM heart_rate GROUP BY status;
```

A green dry-run returns rows with `source_record_uid` populated and the
`status` column populated on the v1 dedicated tables. If you ran the
self-host dry-run with a sample batch that includes `deletions`, also confirm
the targeted UUIDs flipped from `active` to `superseded` (and only those — the
route applies `WHERE status='active'`).

#### 5. Android adoption — follow-up

Android is **not** on the v2 wire yet (Slice 8 of Plan 2026-09-03). Android
clients continue to use `/api/apple/batch` (v1) unchanged.


## iOS app compatibility

The `POST /api/apple/batch` / `GET /api/apple/status` / `GET /api/health` contract
is **frozen and unchanged** — the live App Store HealthSave binary keeps working
across this upgrade. If you set an `API_KEY`, configure the same key in the app.
