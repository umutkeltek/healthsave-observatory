# Direct plugins: Whoop & Amazfit

Some sources do not go through Apple Health at all. The **Whoop** and
**Amazfit / Zepp** plugins are *poll-based* `Source` plugins: the worker pulls
data directly from the vendor's cloud and writes it into the same per-metric
TimescaleDB tables the Apple Health bridge writes to. No Apple device is
required — these are a concrete demonstration that Apple is the on-ramp, not the
boundary.

Both are **early** and both are **bring-your-own-credentials**: you supply your
own developer app or extracted token, the Observatory holds it encrypted at rest
(Fernet, keyed by `HDH_TOKEN_ENC_KEY`), and polling is disabled until you opt in
with a cron schedule. Source identity is preserved downstream, so Whoop rows are
distinguishable from iOS rows in Grafana filters and Home Assistant entities via
the [Source / Device / Stream](../concepts/source-device-stream.md) model.

> Run the operator commands below from the repository root, where
> `docker-compose.yml` lives.

## Whoop

OAuth-based poll plugin against the [Whoop developer API](https://developer.whoop.com).
**Status: shipped (early).** You need your own Whoop developer credentials.

### What it emits

- `heart_rate_variability` → `hrv` (RMSSD from recovery)
- `blood_oxygen` → `blood_oxygen` (SpO2 from recovery)
- `body_temperature` → `body_temperature` (skin temperature from recovery)
- `workouts` → `workouts` (duration, average/max HR, calories, distance, source label)
- `strain` → `quantity_samples` (daily strain summary)
- `recovery_score`, `resting_heart_rate` → `quantity_samples` (provider recovery aggregates)
- `sleep_duration_hours`, `sleep_efficiency_percentage`, `sleep_respiratory_rate` → `quantity_samples` (Whoop session aggregates)

### Setup

1. Register a developer app at <https://developer.whoop.com> and note the client ID + secret.
2. Set these in `.env`:

   ```
   WHOOP_CLIENT_ID=fc25041a-...
   WHOOP_CLIENT_SECRET=...
   WHOOP_REDIRECT_URI=https://your-host/api/v2/whoop/callback
   HDH_TOKEN_ENC_KEY=<run the generate_key command below>
   ```

   Generate the token encryption key:

   ```bash
   docker compose run --rm --no-deps --build api python -c "from auth import generate_key; print(generate_key())"
   ```

3. Run migration 008 so the `oauth_tokens` + `oauth_token_events` tables exist:

   ```bash
   docker compose exec -T db psql -U healthsave -d healthsave < db/migrations/008_oauth_tokens.sql
   ```

4. Run the one-time authorize CLI to bind a Whoop account:

   ```bash
   docker compose run --rm --build api python scripts/whoop_authorize.py
   ```

   It prints the Whoop authorize URL, opens a browser, waits for you to paste the
   `code` query parameter from the redirect URL, exchanges it for a token, and
   persists the encrypted pair plus an `authorized` audit event. Re-running the
   script overwrites the stored token — useful if the refresh chain breaks.

5. Set `WHOOP_POLL_CRON` in `.env` (for example `*/30 * * * *`) and restart the
   worker. Leave it blank to keep Whoop polling disabled.

Refresh tokens are rotated atomically: a successful refresh invalidates Whoop's
previous pair, so the new pair is written in a single transaction with a
`refreshed` audit event.

## Amazfit / Zepp

Poll plugin against Zepp's (formerly Huami / Mi Fit) cloud. **Status: shipped
(early)** — and read the caveat before enabling.

> **Read this first.** Zepp does not publish a public API and is actively
> unsupported as a third-party integration. The plaintext-password login flow
> the plugin originally shipped was demonstrated dead in 2026-05. The current
> design follows the community-converged position: **do not run a password login
> inside this service.** You acquire an `app_token` externally and hand it in; on
> expiry the worker fails loud and you re-extract. If long-term stability matters
> more than rich data, consider [Gadgetbridge](https://gadgetbridge.org) (Android,
> direct BLE, no cloud) and a one-off CSV export instead.

### What it emits

- `measurement.heart_rate` — per-minute BPM when continuous HR is enabled
- `measurement.blood_oxygen` — SpO2 readings (newer Amazfit models)
- `measurement.sleep_analysis` — sleep stages from the band daily summary
- `measurement.stress` — all-day stress events
- `measurement.daily_activity` — band daily summary + training-load aggregates

### Setup

**Step 1 — acquire an `app_token`.** Recommended path is the maintained
`huami-token` PyPI CLI (the plaintext password is consumed only by this external
CLI; the Observatory never sees it):

```bash
pipx install huami-token            # one time
huami-token --method amazfit \
  --email <your-zepp-email> \
  --password <your-zepp-password> \
  --no_logout > /tmp/zepp-auth.txt
```

The output contains an `app_token=...` line and a `User id: <digits>` line. If
`huami-token` fails, you can instead capture the Zepp app's HTTPS traffic with a
proxy (Proxyman, Charles, mitmproxy) and read the `apptoken` request header plus
the numeric user id and regional host suffix.

**Step 2 — register the token with the Observatory.** From the huami-token
output file:

```bash
docker compose run --rm --build api python scripts/amazfit_authorize.py --from-huami-token-stdout /tmp/zepp-auth.txt --region us
```

Or pass the values manually:

```bash
docker compose run --rm --build api python scripts/amazfit_authorize.py --from-token <T> --user-id <U> --region us
```

The token is persisted via the `oauth_tokens` table (provider `"amazfit"`,
encrypted at rest with `HDH_TOKEN_ENC_KEY`).

**Step 3 — enable the worker poll.** Set `AMAZFIT_POLL_CRON` in `.env`
(e.g. `*/30 * * * *`) and restart the worker. No data flows until you have run
the authorize CLI once *and* set a non-empty cron.

**Step 4 — re-extract on expiry.** The token has a finite TTL (hedged to ~25
days; observed claims have been ~11 days). On expiry the worker logs a fail-loud
`AmazfitAuthError("token expired — re-extract")`. Re-run Step 1 → Step 2 to
refresh.

## Why these are plugins

Both write through the same `IngestStorage` protocol the Apple Health bridge
uses and normalize into the same `heart_rate` / `blood_oxygen` /
`sleep_sessions` schema. They differ only above the SDK: Whoop is OAuth 2.0 with
refresh tokens; Zepp is a single externally-extracted token with no refresh. The
`Source` base class is the shared seam — implement it and you can poll any
wearable cloud yourself. See [the capture index](./index.md) and the protocol
docs in [`API.md`](../../API.md).
