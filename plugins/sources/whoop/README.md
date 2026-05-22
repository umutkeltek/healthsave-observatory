# Whoop (HealthSave bridge)

Poll-based `Source` plugin that ingests recovery, sleep, workout, and cycle data from the [Whoop developer API](https://developer.whoop.com) into the same per-metric Timescale tables the Apple Health plugin writes.

## Status

**P2 (2026-05).** Manifest, OAuth helpers, token storage, paginated fetchers, normalizers, end-to-end `WhoopSource.ingest`, the authorize CLI, and env-gated worker polling all ship.

## What it emits

- `measurement.heart_rate` — resting HR, average HR per workout
- `measurement.hrv` — RMSSD per cycle
- `measurement.sleep_analysis` — sessions + per-stage durations
- `measurement.workouts` — duration, HR zones, calories, strain
- `measurement.recovery` — recovery score, SpO2, skin temp
- `measurement.strain` — daily strain summary

## Setup

1. Register a developer app at <https://developer.whoop.com> and note the client ID + secret.
2. Set the following in `.env`:

   ```
   WHOOP_CLIENT_ID=fc25041a-...
   WHOOP_CLIENT_SECRET=...
   WHOOP_REDIRECT_URI=https://your-host/api/v2/whoop/callback
   HDH_TOKEN_ENC_KEY=<run `python -c "from auth import generate_key; print(generate_key())"`>
   ```

3. Run migration 008 so the `oauth_tokens` + `oauth_token_events` tables exist.

   ```bash
   docker compose exec -T db psql -U healthsave -d healthsave < db/migrations/008_oauth_tokens.sql
   ```

4. Run the one-time authorize CLI to bind a Whoop account:

   ```bash
   python scripts/whoop_authorize.py
   ```

   It prints the Whoop authorize URL, opens a browser, waits for you to paste the `code` query parameter from the redirect URL, exchanges it for a token, and persists the (encrypted) pair plus an `authorized` audit event. Re-running the script overwrites the stored token row — useful if the refresh chain breaks.

5. Set `WHOOP_POLL_CRON` in `.env` (for example `*/30 * * * *`) and restart the worker. Leave it blank to keep Whoop polling disabled.

## Architecture

- OAuth tokens are encrypted at rest with Fernet using `HDH_TOKEN_ENC_KEY`. Plaintext only exists inside the Python process at refresh / fetch time.
- Refresh tokens are rotated atomically: a successful refresh invalidates Whoop's previous pair, so `put_token` writes the new pair in a single transaction and appends a `refreshed` event.
- Each normalized row routes through the same `IngestStorage` Protocol used by the Apple Health plugin. Source identity (`source="whoop"`) is the only thing that distinguishes Whoop rows from iOS rows downstream.

## Why a plugin and not a route handler

Whoop is a *poll-based* source (the worker pulls). The Apple Health plugin is a *push-based* source (the iOS app pushes via `POST /api/apple/batch`). The `Source` base class supports both because the runtime that invokes `ingest()` is what differs (scheduler vs. route handler), not the contract. Keeping both as plugins lets a future second-party backend implement either pattern without forking the ingest path.
