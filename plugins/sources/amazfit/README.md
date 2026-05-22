# Amazfit / Zepp (HealthSave bridge)

Poll-based `Source` plugin that ingests heart rate, SpO2, stress, sleep, and daily activity data from Zepp's (formerly Huami / Mi Fit) cloud into the same per-metric Timescale tables HealthSave / Whoop / Garmin write to.

## Status

**P6-a scaffold (2026-05).** Manifest, OAuth helpers, and authentication scaffolding ship in this directory. The data-fetch loop (`fetch.py`), normalizers (`normalize.py`), end-to-end `ingest()`, authorize CLI, and worker registration land in P6-b through P6-f.

## ⚠️ Stability warning — read before enabling

Zepp does not publish a public API. This plugin talks to reverse-engineered cloud endpoints. Expect:

- **Wire shape changes every 6–12 months.** Each release of the Zepp app (iOS / Android) may flip a field name, change response structure, or rotate base64 blob encodings. Per-fetcher tests will catch most of these; some will require a code change to follow Zepp's drift.
- **Auth flow has changed 3 times across rebrands** (Mi Fit → Huami → Zepp). The current flow (huami-token style) is what works today.
- **Rate limiting.** Don't poll faster than every ~15 minutes per account. The default cron in the worker scheduler is `*/30 * * * *`.

If long-term stability matters more than rich data, consider [Gadgetbridge](https://gadgetbridge.org) (Android, direct BLE, no cloud) and a one-off CSV export rather than this plugin.

## What it emits

- `measurement.heart_rate` — per-minute BPM when continuous HR is enabled
- `measurement.blood_oxygen` — periodic overnight SpO2 readings (newer models only — Band 7+, GTS 2+, GTR 2+)
- `measurement.sleep_analysis` — session-level stages (Light / Deep / REM / Awake)
- `measurement.stress` — periodic stress score (newer models only)
- `measurement.daily_activity` — steps, distance, calories, resting HR (daily summaries)

## Setup

1. Create or use an existing Zepp account at <https://zepp.com>. The plugin authenticates as your account — there is no "developer app" registration.
2. Set the credentials in `.env`:

   ```
   AMAZFIT_EMAIL=you@example.com
   AMAZFIT_PASSWORD=<your Zepp account password>
   AMAZFIT_REGION=us            # us | eu | cn (default us)
   HDH_TOKEN_ENC_KEY=<run `python -c "from auth import generate_key; print(generate_key())"`>
   ```

   The password is MD5-hashed at the wire boundary before transmission (Zepp's endpoint expects that shape). It is **never** persisted to disk — only the resulting `app_token` is stored, encrypted, in the `oauth_tokens` table.

3. Run migration 008 so the `oauth_tokens` table exists (no separate migration for Amazfit — it reuses the table Whoop uses, with `provider = "amazfit"`).

4. P6-e will add a CLI:

   ```bash
   python scripts/amazfit_authorize.py
   ```

   For now (P6-a), discovery and manifest can be exercised by tests but the runtime ingest is intentionally NotImplementedError.

## Architecture

- **Auth** — two-step huami-token flow: POST email + MD5(password) → `login_token`, then GET token exchange → `app_token`. Lifetime ~25 days (hedged from the historical ~30 day Zepp behaviour). The `app_token` is the persisted secret; no refresh token primitive exists. Re-running the login flow on expiry replaces the row idempotently.
- **Storage** — reuses the same `oauth_tokens` / `oauth_token_events` tables as Whoop, with `provider = "amazfit"`. `metadata` carries `base_url` + `region` + `user_id` so the fetch loop doesn't need to re-load config.
- **Polling** — env-gated via `AMAZFIT_POLL_CRON` in the worker (P6-f). No data flows until the operator runs the CLI once and sets a non-empty cron.

## Why a separate plugin and not a Whoop fork

Whoop is OAuth 2.0; Zepp is a proprietary token-exchange. The `Source` base class is the right shared seam — both plugins write through the same `IngestStorage` Protocol, normalize into the same `heart_rate` / `hrv` / `sleep_sessions` schema, and reuse the same `oauth_tokens` table for credential persistence. Above the SDK, the wire-shape code is genuinely different.
