# Whoop (HealthSave bridge)

Poll-based `Source` plugin that ingests recovery, sleep, workout, and cycle data from the [Whoop developer API](https://developer.whoop.com) into the same per-metric Timescale tables the Apple Health plugin writes.

## Status

**P1 scaffold (2026-05).** Manifest, OAuth helpers, and token storage scaffolding ship in this directory. The data-fetch loop (`fetch.py`) and the worker job registration land in P2.

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

4. P2 will add a CLI / admin endpoint that walks the authorization-code grant. Until then, the plugin's discovery and manifest can be exercised by tests but the runtime ingest stays disabled.

## Architecture

- OAuth tokens are encrypted at rest with Fernet using `HDH_TOKEN_ENC_KEY`. Plaintext only exists inside the Python process at refresh / fetch time.
- Refresh tokens are rotated atomically: a successful refresh invalidates Whoop's previous pair, so `put_token` writes the new pair in a single transaction and appends a `refreshed` event.
- Each normalized row routes through the same `IngestStorage` Protocol used by the Apple Health plugin. Source identity (`source="whoop"`) is the only thing that distinguishes Whoop rows from iOS rows downstream.

## Why a plugin and not a route handler

Whoop is a *poll-based* source (the worker pulls). The Apple Health plugin is a *push-based* source (the iOS app pushes via `POST /api/apple/batch`). The `Source` base class supports both because the runtime that invokes `ingest()` is what differs (scheduler vs. route handler), not the contract. Keeping both as plugins lets a future second-party backend implement either pattern without forking the ingest path.
