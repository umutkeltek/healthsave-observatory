# Polar AccessLink Source

Poll-based Polar AccessLink source plugin.

Status: first slice. It uses BYO OAuth credentials, registers the user with
Polar AccessLink, polls `GET /v3/exercises`, and writes:

- `workouts`
- `exercise_duration_seconds`

It does not use the deprecated exercise transaction endpoint. FIT/TCX details,
webhooks, and per-sample streams are later slices.

## Setup

1. Create a Polar AccessLink client.
2. Set:

```bash
POLAR_CLIENT_ID=
POLAR_CLIENT_SECRET=
POLAR_REDIRECT_URI=
HDH_TOKEN_ENC_KEY=
```

3. Run migrations so `oauth_tokens` and fusion metadata exist.
4. Run:

```bash
docker compose run --rm --build api python scripts/polar_authorize.py
```

The script prints the Polar Flow authorization URL. After approval, paste the
`code` query parameter from the redirect URL. The script exchanges the code,
registers the user through `/v3/users`, and stores the token encrypted in the
shared OAuth token table.

5. Set `POLAR_POLL_CRON`, for example:

```bash
POLAR_POLL_CRON=*/30 * * * *
```

Restart the worker. Leave it blank to keep polling disabled.

## Architecture

Polar is a direct Observatory source plugin. Android remains a Health Connect
relay and never grows Polar OAuth code. The plugin writes through the existing
`IngestStorage` port; fusion with relayed Health Connect rows is handled by the
canonical observation fusion metadata/read path, not by this plugin.
