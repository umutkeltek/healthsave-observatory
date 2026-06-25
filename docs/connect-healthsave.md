# Connect HealthSave

The easiest way to push Apple Health data into HealthSave Observatory is the [**HealthSave** iOS app](https://apps.apple.com/app/id6759843047).

HealthSave expects a **base server URL** and appends API paths itself.

## Pair The App

1. Open **HealthSave -> Settings -> Server Sync**.
2. Set **Server URL** to the backend URL printed by `healthsave doctor`, for example `http://<server-lan-ip>:8000`.
3. Optional: set your **API key** if you configured one.
4. Tap **Sync New Data**.

iOS will not sync to `localhost` from the phone; use the backend's LAN IP. Running `healthsave doctor` prints the exact URL to paste into the app.

Manual sync, **Sync New Data**, works for testing without Pro unlock. Ongoing background uploads need the one-time Pro unlock in the iOS app.

## Building Another Client?

The batch ingest endpoint is:

```text
http://<server-lan-ip>:8000/api/apple/batch
```

This is the **frozen v1 compatibility contract**. Match it exactly or the existing app compatibility path will break. The full request/response contract, including the exact `/api/apple/status` shape the iOS app parses directly, is documented in [v1 Apple contract](api/v1-apple-contract.md).
