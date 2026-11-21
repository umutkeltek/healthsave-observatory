# Connect HealthSave

The easiest way to push Apple Health data into HealthSave Observatory is the [**HealthSave** iOS app](https://apps.apple.com/app/id6759843047).

HealthSave expects a **base server URL** and appends API paths itself.

## Pair The App

With the QR code (works without Pro):

1. On the server, run `healthsave pair`. It prints the server URL, the API key and a QR code.
2. Scan the QR code with the iPhone Camera. HealthSave opens **Server Sync** with the URL and key filled in.
3. Tap **Sync Latest Changes**, or **Backfill Past Data** to send your whole history.

By typing it in (needs Pro):

1. Open **HealthSave -> Settings -> Server Sync**.
2. Set **Server URL** to the backend URL printed by `healthsave pair`, for example `http://<server-lan-ip>:8000`.
3. Set the **API key** that `healthsave pair` prints. Setup generates one, and the server refuses requests without it.
4. Tap **Sync Latest Changes**.

iOS will not sync to `localhost` from the phone; use the backend's LAN IP. Running `healthsave doctor` prints the exact URL to paste into the app.

## Free and Pro

Observatory is free. In the HealthSave app, HealthSave Pro is a one-time purchase (no subscription).

| In the app | Without Pro | With Pro |
|---|---|---|
| Send data by hand (**Sync Latest Changes**, **Backfill Past Data**) | Yes, on the Server Sync screen that opens after you scan the pairing QR code. To send again later, scan the code again | Yes, any time |
| Open **Settings -> Server Sync** | Shows the Pro offer | Yes |
| Automatic sync: in the background, and each time you open the app | No | Yes. iOS decides when background work runs, so it can be hours late |
| Sync alerts when sending stops | No | Yes |
| Home Assistant sensors from the app | No | Yes |
| What is sent | Your Data Scope choice, same as Pro | Your Data Scope choice |

## Building Another Client?

The batch ingest endpoint is:

```text
http://<server-lan-ip>:8000/api/apple/batch
```

This is the **frozen v1 compatibility contract**. Match it exactly or the existing app compatibility path will break. The full request/response contract, including the exact `/api/apple/status` shape the iOS app parses directly, is documented in [v1 Apple contract](api/v1-apple-contract.md).
