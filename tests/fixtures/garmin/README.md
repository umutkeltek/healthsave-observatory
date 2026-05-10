# Garmin import fixtures

All files in this directory are **synthetic** — fabricated heart-rate
values, step totals, and sleep stage windows that resemble Garmin Connect
exports without containing real user data. Timestamps are 2026-dated to
avoid collisions with any real activity in test databases.

| File | Format | Coverage |
|------|--------|----------|
| `sample.tcx` | TCX 1.0 (Garmin namespace) | 6 trackpoints, heart_rate field |
| `sample_steps.json` | Garmin wellness daily-steps JSON | 7 days of `{calendarDate, totalSteps}` |
| `sample_sleep.json` | Garmin sleep export with `sleepLevels` | One night, 8 stage windows |

FIT parsing is exercised in `tests/test_import_garmin.py` via a mocked
`fitparse.FitFile` rather than a binary fixture, since synthesizing a
valid FIT file is non-trivial and the parser logic is straightforward.
