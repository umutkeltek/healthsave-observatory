# Google Health API Source

Experimental Google Health API source plugin.

Current slice:

- OAuth authorization-code flow with offline refresh tokens.
- Polls `GET https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints`.
- Normalizes Google `steps` data points into the existing `step_count` ingest path.
- Uses the shared encrypted `oauth_tokens` store and the worker scheduler.

It intentionally does not implement a legacy Fitbit Web API adapter. The source
id is `google-health-api`; Fitbit can appear later as `origin_provider` or
application/device provenance inside Google Health data points.

Required env:

```dotenv
GOOGLE_HEALTH_CLIENT_ID=
GOOGLE_HEALTH_CLIENT_SECRET=
GOOGLE_HEALTH_REDIRECT_URI=
GOOGLE_HEALTH_POLL_CRON=
HDH_TOKEN_ENC_KEY=
```

Run the one-time OAuth binding:

```bash
python scripts/google_health_authorize.py
```

Leave `GOOGLE_HEALTH_POLL_CRON` blank to disable scheduled polling.
