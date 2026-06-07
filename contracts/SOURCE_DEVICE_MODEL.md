# Source / Device / Stream model — locked design

**Status:** Locked 2026-06-08 via Oracle (GPT‑5.5 Pro, extended) consult `healthsave-source-device-separation-3`. Builds on [[project_datahub_v2_architecture_decisions]] (canonical-Observation spine). This is the canonical per-device/per-source separation model for HealthSave (iOS) → datahub → Home Assistant.

## Final locked rule

- **Source** = ingress *integration* ("how did this enter datahub?") — e.g. `apple-healthkit-ios` (iOS push), `whoop-oauth` (worker poll), `amazfit-oauth`, `csv-import`.
- **Device** = physical/logical *emitter* ("what generated it?") — Apple Watch, iPhone, Whoop band, Oura ring.
- **Stream** (`source_device_stream`) = the *join* of source + device/origin ("this device as seen through this integration") — e.g. "Apple Watch via HealthKit", "WHOOP via HealthKit", "WHOOP via Whoop OAuth". **This is the new concept** — the missing join between the already-designed `Source` and `Device` contracts.
- **HealthKit sub-source** (`HKSource.name`/bundle) = a **provenance alias used to resolve a stream/device — NOT a Source.** Display names are never identity again.
- **Home Assistant entities key on canonical stream UUIDs, not display-name slugs.**

The same Whoop band legitimately yields **two streams** (via-HealthKit + via-direct-poll); both are kept with provenance, and **fused reads** dedupe them.

## Identity & dedup

- **exact_ingest_key** (idempotency, `UNIQUE(owner_id, exact_ingest_key)`): `provider_object_id` → else `hk_uuid` → else `hk_metadata_sync_identifier+version` → else composite(`source_id,metric_id,stream_id,start,end,value,unit,raw_payload_hash`).
- **semantic_key** (fusion only): provider semantic id, or `(owner,origin_provider,device_id,metric,normalized start/end/value/unit)`; **null** otherwise. **Never dedupe across different physical devices or providers on matching timestamp+value** (Apple-Watch HR and Whoop HR can both be 72 bpm at 10:00 — distinct observations).
- **Primary selection** (keep all variants, mark one `is_primary`): provider-direct-with-IDs > HealthKit-with-UUID/device > HK source-scoped statistics > legacy name-string > unknown(aggregate-only). **Whoop direct > Whoop via HealthKit.** For Apple totals: **HealthKit all-source aggregate > sum of source-scoped components** (steps/energy overlap).

## iOS wire-format additions (`/api/apple/batch`, additive only — v1 frozen)

Keep `metric/batch_index/total_batches/samples/date/qty/source` unchanged. Add (older servers ignore unknowns):
- **Batch:** `client_schema_version`, `bridge_install_id` (Keychain UUID — provenance, NOT identity), `captured_at`, `timezone`.
- **Per-sample:** `hk_uuid`, `start_date`, `end_date`, `source_name`, `source_bundle_id`, `source_revision_{version,product_type,operating_system}`, `device_{name,manufacturer,model,hardware_version,firmware_version,software_version,local_identifier,udi_device_identifier}`, `metadata_sync_{identifier,version}`, `aggregation_{scope,method}`.
- **Minimum deterministic set:** `hk_uuid`, `source_bundle_id`, `source_revision_product_type`, `device_local_identifier` OR `device_udi_device_identifier`, `metadata_sync_*` when present.
- Hash hardware ids at rest (`sha256(deployment_salt + raw)`); never expose raw device ids to MQTT/HA.

**Cumulative metrics (steps/energy):** keep sending the all-source row; ALSO send per-source rows via HealthKit `separateBySource` — but only after `GET /api/apple/capabilities` advertises `accepts_source_scoped_statistics:true` (prevents old self-hosted backends double-counting). Aggregate read still uses the all-source total.

## Capability registry (the "which integration provides which data")

Plugin `plugin.yaml` manifests = source of truth (typed capability objects; keep the old flat `emits:` list working via startup normalization) → loaded into DB registry tables: `source_plugins`, `source_capabilities`, `source_instances`, `devices`, `source_device_streams`, `source_aliases`. Each capability declares `metric_id, value_type, cadence, source_granularity, ha.{expose,projection,unit,state_class}` + `gather_method` + `injection_path` + `identity` key priority. Rename Whoop plugin id → `whoop-oauth` (alias `whoop-healthsave`). CI validates manifests vs JSON-schema + metric registry; runtime quarantines unknown plugin_id/metric_id.

## datahub wiring

- Ingest → **resolver + dual-writer**: parse v1(+v1.1) → resolve Source/origin-alias/Device/Stream → compute exact+semantic keys → write v1 table (compat) AND `canonical_observations` (+ `stream_id`, dedup keys, `is_primary`).
- Add nullable canonical columns to every v1 metric table (`canonical_{source,device,stream}_id`, `exact_ingest_key`, `semantic_key`, `provenance`); keep `source_id TEXT` as `raw_source_label`.
- Direct plugins stop writing literal `"Whoop"`/`"Amazfit"` as identity — resolve via registry, write canonical ids + keep the literal as a compat label.
- `recovery`/`stress`/`sleep_stages` gain canonical source/stream columns (new writes require them; old rows → `legacy-unattributed` Source, excluded from per-stream HA).

## Home Assistant (3 layers)

1. Legacy aggregate parent entities — **keep** (don't break dashboards).
2. **Canonical stream devices** — one HA device per `source_device_stream`; `StreamHealthSnapshot` replaces `SourceHealthSnapshot`; `unique_id = healthsave:stream:<uuid>:<metric>`, state topic `<prefix>/stream/<uuid>/state` — identity stable across display-name changes. Deprecate `source_slug()`.
3. Optional fused physical-device entities (only when device identity confidence is strong/medium).
- **Per-source coverage is registry-driven** (publish every metric where capability `ha.expose` + projection + fresh value) — not the hardcoded 4. Covers HR, HRV, steps, calories, sleep dur/eff, blood_oxygen, **body_temperature, respiratory_rate**, recovery, strain, stress, sleep-stage minutes (as scalar projections).

## Migration / fusion-at-read

Resolver priority: strong provider IDs → HK device ids → HK bundle+revision → HK bundle → alias table → legacy name. Backfill: create canonical Sources (`apple-healthkit-ios`, `whoop-oauth`, `amazfit-oauth`, `legacy-unattributed`) + alias rows from existing `source_id TEXT` → backfill canonical columns + `canonical_observations`. Three read models: `raw_stream_observations` (no dedup), `fused_device_observations` (dedup per device), `fused_owner_observations` (owner aggregate, metric-specific rules).

## Phased plan

1. **datahub identity foundation (FIRST, safe-additive):** registry tables + canonical columns + `apple-healthkit-ios` manifest + `whoop-oauth` rename + resolver + dual-write. → existing raw names resolve to stable canonical streams; HA can stop slug-keying **before any iOS release**.
2. Canonical HA stream publishing (StreamHealthSnapshot, stream-UUID unique_id); keep slug entities one window.
3. iOS v1.1 additive metadata (the fields above).
4. Source-scoped cumulative metrics (capability handshake).
5. Direct-plugin canonicalization (Whoop/Amazfit resolve; recovery/stress/sleep_stages columns).
6. Backfill + fusion views.
7. Legacy cleanup (contract-affecting; later — stop slug entities, keep aggregate parents, keep v1 batch + raw_source_label forever).

## Safe vs breaking

Safe-additive (do): optional `/api/apple/batch` fields, registry tables, nullable canonical columns, dual-write, canonical HA stream entities. Breaking (don't): remove aggregate HA entities, rename/remove `source` in iOS payload, require iOS to send canonical UUIDs, send source-scoped step rows to old backends without the capability gate, rename plugin id without alias.

---
Full Oracle transcript: `~/.oracle/sessions/healthsave-source-device-separation-3/output.log` (reattach: `oracle session healthsave-source-device-separation-3`).
