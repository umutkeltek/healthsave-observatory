# Multi-user / Household

The Observatory supports more than one person on a single install. Every metric table carries an `owner_id` UUID, so multiple residents can share one backend without their data colliding.

## Single-user installs (default)

Nothing to configure. When the `X-User-Id` header is absent, ingest writes under the sentinel UUID `00000000-0000-0000-0000-000000000001`, and the schema-level default backfills any pre-migration rows to the same value. Existing single-user installs keep working untouched.

## Splitting a household across residents

1. **Pick a UUID per person.** Any v4 UUID works:

   ```bash
   python -c "import uuid; print(uuid.uuid4())"
   ```

2. **Send it as a header.** Configure each HealthSave client / import script to send that UUID as the `X-User-Id` header on every `POST /api/apple/batch` call.

3. **Filter dashboards by owner.** In Grafana, add a dashboard variable bound to:

   ```sql
   SELECT DISTINCT owner_id FROM heart_rate
   ```

   then drop `WHERE owner_id = '$owner'` into each panel query.

## How isolation holds

The unique indexes on every metric table include `owner_id`, so two residents can have a sample at the same `(time, device_id)` without collisions, and re-syncing from one client stays idempotent. If you skip step 2, existing single-user installs keep working unchanged.

## See also

- [Deployment](deployment.md) — pointing each client at the server
- [Backups & migrations](backup-and-migrations.md) — the migration that added `owner_id`
