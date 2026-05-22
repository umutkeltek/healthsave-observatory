# Amazfit / Zepp (HealthSave bridge)

Poll-based `Source` plugin that ingests heart rate, SpO2, stress, sleep, and daily activity data from Zepp's (formerly Huami / Mi Fit) cloud into the same per-metric Timescale tables HealthSave / Whoop / Garmin write to.

## ⚠️ Read this before enabling

**Zepp does not publish a public API and is actively unsupported as a third-party integration.** The plaintext-password `v2/client/login` flow this plugin originally shipped (P6-a) was demonstrated dead on 2026-05-22 — fresh credentials returned `HTTP 400 {"error_code":"0100"}` and the legacy scheduler that used the same flow had been silently failing hourly for at least 13h.

The current `H-revise` design follows the community-converged position (see [huami-token issue #119](https://codeberg.org/argrento/huami-token/issues/119) and [zepp-health-cli](https://github.com/m4ary/zepp-health-cli)): **do not run a password login inside this service**. Operators acquire an `app_token` externally and hand it in. On expiry, the worker fails loud and the operator re-extracts.

If long-term stability matters more than rich data, consider [Gadgetbridge](https://gadgetbridge.org) (Android, direct BLE, no cloud) and a one-off CSV export rather than this plugin.

## Status

- **H-revise (2026-05).** auth.py rewritten: no `login()`, no plaintext password handling. Token-import helpers (`token_from_app_token_string`, `token_from_huami_token_output`, `token_from_env`) materialize an `OAuthToken` from an externally-acquired `app_token` + `user_id` + region.
- `AmazfitSource.ingest` still raises `NotImplementedError` until the `H-ingest` commit lands the fetch + normalize + write loop.
- `H-fetch` ships paginated fetchers against `api-mifit-us3.zepp.com`. `H-normalize` ships normalizers. `H-cli` ships the authorize CLI. `H-worker` wires the worker poll job.

## What it emits

- `measurement.heart_rate` — per-minute BPM when continuous HR is enabled (path `/users/<id>/heartRate`)
- `measurement.blood_oxygen` — SpO2 readings from `/users/<id>/events?eventType=blood_oxygen` (newer Amazfit models)
- `measurement.sleep_analysis` — extracted from `band_data.json?query_type=summary` (sleep stages are bundled inside the band daily summary in the current API)
- `measurement.stress` — `/users/<id>/events?eventType=all_day_stress`
- `measurement.daily_activity` — `/v1/data/band_data.json` summary + `/v2/watch/.../SPORT_LOAD` for training-load aggregates

## Setup (H-revise procedure)

### Step 1 — acquire an `app_token`

**Option A (recommended, no proxy install):** use the maintained `huami-token` PyPI CLI.

```bash
pipx install huami-token            # one time
huami-token --method amazfit \
  --email <your-zepp-email> \
  --password <your-zepp-password> \
  --no_logout > /tmp/zepp-auth.txt
```

The output contains two lines you care about:

```
app_token=<base64-ish blob>
... Logged in! User id: <digits>
```

The plaintext password is consumed only by the external CLI; the datahub never sees it.

**Option B (if huami-token also fails):** capture the Zepp iOS / Android app's HTTPS traffic via a proxy (Proxyman, Charles, mitmproxy). Any request to `api-mifit-*.zepp.com` carries an `apptoken: <token>` request header. Note that value plus the numeric user id (in URL paths like `/users/<id>/...`) and the regional host suffix (`-us3` / `-de` / no suffix).

### Step 2 — register the token with the datahub

```bash
# from the huami-token output file:
python scripts/amazfit_authorize.py --from-huami-token-stdout /tmp/zepp-auth.txt --region us

# or manually:
python scripts/amazfit_authorize.py --from-token <T> --user-id <U> --region us
```

The authorize CLI persists the token via the `oauth_tokens` table (provider `"amazfit"`, encrypted at rest with `HDH_TOKEN_ENC_KEY`).

### Step 3 — enable the worker poll

Set `AMAZFIT_POLL_CRON` in the datahub env (e.g. `*/30 * * * *`) and restart the worker. The plugin will start polling on the next tick.

### Step 4 — re-extract on expiry

The token has a finite TTL (we hedge to 25 days; observed `expiration` claims have been ~11 days). On expiry the worker logs a fail-loud `AmazfitAuthError("token expired — re-extract")`. Re-run Step 1 → Step 2 to refresh.

## Architecture

- **Auth boundary.** `auth.py` exposes pure helpers that convert an externally-acquired `app_token` into an `OAuthToken`. No HTTP. No password handling. No retry/refresh logic.
- **Persistence.** Reuses the `oauth_tokens` / `oauth_token_events` tables Whoop uses, with `provider = "amazfit"`. `metadata` carries `base_url` + `region` + `user_id` so the fetch loop doesn't need to re-load config.
- **Fetch headers.** Every data-API call sends `apptoken: <token>`, `appname: com.huami.midong`, `appplatform: ios_phone`, `x-request-id: <uuid>`, and a `r=<uuid>` query parameter (per-call). These were established via the H-revise probe.
- **Polling.** Env-gated via `AMAZFIT_POLL_CRON`. No data flows until the operator runs the authorize CLI once AND sets a non-empty cron.

## Why a separate plugin and not a Whoop fork

Whoop is OAuth 2.0 with refresh tokens; Zepp is a proprietary single-token-with-no-refresh primitive driven by an externally-extracted credential. The `Source` base class is the right shared seam — both plugins write through the same `IngestStorage` Protocol, normalize into the same `heart_rate` / `blood_oxygen` / `sleep_sessions` schema, and reuse the same `oauth_tokens` table for credential persistence. Above the SDK, the auth surfaces are genuinely different.
