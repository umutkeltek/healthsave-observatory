# Importers: Garmin & Samsung

When a source is file-based rather than a live cloud API, HealthSave Observatory
ships **CLI importers** that sideload exports into the same `/api/apple/batch`
endpoint the iOS app uses. Because they ride the normal ingest path,
deduplication, the audit log, sync receipts, and dashboards all behave
identically — no Apple device required. Both importers are **shipped**.

The two importers are:

- `scripts/import_garmin.py` — for Garmin Connect exports.
- `scripts/import_samsung.py` — for Samsung Health / Huawei Health exports via
  the Android `Health Sync` app.

> Run these from the repository root. Both support `--dry-run`, which parses,
> counts, and logs without sending any traffic — use it to sanity-check a fresh
> export before posting real data.

## Garmin Connect

`scripts/import_garmin.py` reads the bulk **"Export Your Data"** ZIP, individual
FIT/TCX activity files, and the JSON files Garmin includes for daily steps and
sleep stages, then POSTs them to `/api/apple/batch`.

### Install the optional FIT parser

FIT activity files need the optional `garmin` extra once (TCX, JSON, and ZIP
parsing use only the standard library):

```bash
pip install -e ".[garmin]"   # adds fitparse for FIT activity files
```

### Mapping

| Source | HealthSave metric | Server table |
|--------|-------------------|--------------|
| FIT/TCX heart-rate records | `heart_rate` | `heart_rate` |
| Daily step totals (JSON) | `step_count` | `daily_activity.steps` |
| Sleep stages (JSON) | `sleep_analysis` | `sleep_sessions` + `sleep_stages` |

### Usage

```bash
# Bulk export ZIP — walks every supported file inside
python scripts/import_garmin.py \
  --zip GarminConnect_Export.zip \
  --server http://localhost:8000 \
  --api-key $HDH_API_KEY

# Individual files
python scripts/import_garmin.py --tcx run.tcx --steps-json steps.json --sleep-json sleep.json

# Sanity-check the payload before sending
python scripts/import_garmin.py --tcx run.tcx --dry-run
```

Supported inputs (any combination): `--zip`, `--fit`, `--tcx`, `--steps-json`,
`--sleep-json`.

## Samsung / Huawei Health

`scripts/import_samsung.py` reads the directory layout the Android
[Health Sync](https://healthsync.app/) app produces when exporting Samsung
Health or Huawei Health data, parses each CSV folder into HealthSave-shaped
samples, and sends the same `/api/apple/batch` payload shape as the iOS app.
Source attribution (`Samsung Health` vs. `Huawei Health`) is read from each
file's name and surfaced as the sample's `source` field so downstream dashboards
can split per vendor.

### Supported Health Sync folders

| Folder | HealthSave metric | Server table |
|--------|-------------------|--------------|
| `Health Sync Steps/` | `step_count` | `daily_activity.steps` |
| `Health Sync Heart rate/` | `heart_rate` | `heart_rate` |
| `Health Sync Sleep/` | `sleep_analysis` | `sleep_sessions` + `sleep_stages` |
| `Health Sync Weight/` | `body_mass`, `body_fat_percentage` | `quantity_samples` |
| `Health Sync Oxygen saturation/` | `oxygen_saturation` | `blood_oxygen` |

### Usage

```bash
# Sanity-check the export before sending
python scripts/import_samsung.py /path/to/health-sync-export --dry-run

# Send to a local server
python scripts/import_samsung.py /path/to/health-sync-export \
  --server http://localhost:8000 \
  --api-key $HDH_API_KEY
```

Pass the root export directory (the one containing the `Health Sync ...`
subfolders) as the positional argument. `--batch-size` tunes how many samples
are POSTed per request.

## Why importers ride the same path

Both importers send the frozen `/api/apple/batch` payload shape, so they inherit
idempotent dedup, the `raw_ingestion_log` audit trail, and sync receipts for
free. Each imported row keeps its provenance through the
[Source / Device / Stream](../concepts/source-device-stream.md) model. See the
[capture index](./index.md) for the full source list and [`API.md`](../../API.md)
for the wire contract.
