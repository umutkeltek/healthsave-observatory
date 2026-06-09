# Backups & migrations

TimescaleDB is the only stateful piece of the stack, so backups and schema upgrades both center on the database volume. This page covers updating an existing install, the continuous aggregates that derive metrics, and what to back up.

## Backups

Back up the TimescaleDB Docker volume (`db_data`) regularly. It holds every observation you've captured; everything else in the stack is stateless and rebuilds from the image and `.env`.

- History grows slowly — roughly megabytes per month for one person — so the volume stays light and snapshots are cheap.
- If you run on a VM or NAS, point the volume at a disk that's already in your backup rotation (a ZFS dataset you snapshot, a backed-up directory, etc.).
- For a logical backup, `pg_dump` against the database also works and is portable across TimescaleDB versions.

## Updating existing installs

Fresh installs load `db/schema.sql` automatically. Existing Docker volumes keep their original schema, so the Compose stack runs the migration service **before** the API, worker, agents, or Home Assistant bridge start:

```bash
docker compose up -d --build
```

To run the same migration pass explicitly:

```bash
docker compose run --rm migrate
```

The runner records applied files in `schema_migrations`, so re-runs are safe. Migration files live in `db/migrations/` for review and manual recovery. The current set starts at `db/migrations/001_audit_hardening.sql` and includes later additive upgrades such as `db/migrations/002_analysis_tables.sql` and `db/migrations/008_oauth_tokens.sql`; files apply in filename order.

> Take a backup before a major upgrade. Migrations are additive and re-runnable, but a volume snapshot is your fast rollback path if a deploy goes sideways.

## Derived metrics (continuous aggregates)

The schema includes TimescaleDB continuous aggregates for common derived metrics:

- `hr_hourly` — hourly avg/min/max heart rate
- `sleep_daily` — daily sleep stage breakdown

These keep dashboards responsive at scale by precomputing rollups. Add your own the same way:

```sql
-- Example: weekly HRV trend
CREATE MATERIALIZED VIEW hrv_weekly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 week', time) AS bucket,
    device_id,
    avg(value_ms) AS avg_hrv,
    min(value_ms) AS min_hrv,
    max(value_ms) AS max_hrv
FROM hrv
GROUP BY bucket, device_id
WITH NO DATA;
```

## See also

- [Deployment](deployment.md) — placing the volume on a disk you back up
- [Reverse proxy](reverse-proxy.md) — production posture, including deliberate image upgrades
