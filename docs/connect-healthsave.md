# Connect HealthSave

The easiest way to push Apple Health data into HealthSave Observatory is the
[**HealthSave** iOS app](https://apps.apple.com/app/id6759843047).

HealthSave expects a **base server URL** and appends the API paths itself.

## Pair the app

1. Open **HealthSave → Settings → Server Sync**.
2. Set the **Server URL** to your backend, for example
   `http://your-server-ip:8000`.
3. *(Optional)* Set your **API key** if you configured one in `.env`.
4. Tap **Sync New Data**.

iOS won't sync to `localhost` from the phone — use the backend's LAN IP. Running
`./setup.sh doctor` prints the exact URL to paste in.

Manual sync ("Sync New Data") works for testing without the Pro unlock; ongoing
background uploads need the one-time Pro unlock in the iOS app.

## Building another client?

The batch ingest endpoint is:

```
http://your-server-ip:8000/api/apple/batch
```

This is a **frozen v1 compatibility contract** — match it exactly or it will
break. The full request/response contract, including the exact `/api/apple/status`
shape the iOS app parses directly, is documented in the
[v1 Apple contract](api/v1-apple-contract.md).
