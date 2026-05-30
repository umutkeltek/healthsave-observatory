# Golden HealthSave / Apple Health payload corpus

Frozen, app-shaped `POST /api/apple/batch` request bodies as the HealthSave iOS
app (App Store ID 6759843047) actually sends them. Captured from the real wire
shapes in `apps/api/server/ingestion/` (mappers + parsers) and the existing
contract tests.

## Why this exists

1. **v1 freeze corpus** — `tests/contract/api_v1/test_v1_golden_payloads.py`
   pins these so a refactor that breaks the inbound shape fails loudly.
2. **Phase-1 normalizer fixtures** — when the v2 canonical normalizer lands,
   it maps these exact payloads → canonical `Measurement`s. Same inputs, so the
   normalizer is testable and **replayable** without a device or the live app.
3. **Replay-corpus seed (Decision H)** — every ontology/normalizer change must
   re-run against this corpus and produce an explicit diff.

## The four value shapes (chosen on purpose)

| Fixture | Metric | Exercises |
|---------|--------|-----------|
| `heart_rate_batch.json` | `heart_rate` | instant scalar quantity (`{date, qty}`) |
| `sleep_analysis_batch.json` | `sleep_analysis` | **interval + categorical** (`{startDate, endDate, value}`) |
| `quantity_step_count_batch.json` | `step_count` | daily-total quantity, multi-device |
| `workout_batch.json` | `workouts` | interval **event** with components (duration, energy, distance) |

These four cover the scalar / categorical / event value-types that the current
float-only `value` field cannot represent — the exact gap Phase 1 closes.

> Do not "tidy" these into a single shape. The key-name variation
> (`date` vs `startDate`/`endDate`, `qty` vs `value`) is real HealthKit wire
> reality the server parses via `first_present(...)`.
