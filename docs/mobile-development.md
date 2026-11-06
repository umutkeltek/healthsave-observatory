# Developing HealthSave on iOS and Android

The current iOS app is the product reference. Both apps keep their native UI,
health API, billing and background-work implementations. A shared specification,
fixtures and paired tests keep their behavior aligned. Android system permission
and purchase screens follow Android conventions; app-owned screens should match
the iOS information, hierarchy, content, spacing, colors and interaction outcomes.

An availability flag in `contracts/parity.json` means a capability exists. It does
not prove equivalent behavior or design. `contracts/mobile-acceptance.json` names
the acceptance scenarios, source references, required evidence and known gaps.
Never remove a gap simply because a build or unit test passes.

## One change, both apps

1. Identify the iOS behavior and acceptance scenario before implementation.
   Include empty, loading, error, permission-denied and Pro/free states.
2. For deterministic shared behavior, add cases to
   `contracts/mobile-behavior-cases.json` in this repository. Copy it byte-for-byte
   to both clients. Both native test classes must execute the production code.
   A new suite also requires a consumer on each platform; unknown suites fail.
3. Implement the Android counterpart and any intentional iOS correction in
   separate, linked commits. Keep wire changes under the existing contract rules.
   New metrics require an honest decision for both platforms in `parity.json`.
   Health Connect limitations need evidence, not a substitute with different
   semantics. RMSSD and SDNN remain different metrics.
4. Compare both running apps using the same synthetic data and user state.
   Check light/dark, large text, Arabic RTL, phone and tablet layouts. Review the
   16 supported languages. Store labeled screenshots, observations and differences.
   Shared cases do not replace this visual review.
5. Run the paired verification command. Review physical-device evidence for real
   health permissions, history access, background work and purchase/restore.
6. Close acceptance gaps only with linked evidence. Commit each completed slice
   in its owning repository. Keep unresolved work explicit.

From a workspace containing sibling `datahub`, `ios_app` and `android_app` checkouts:

```sh
cp datahub/contracts/mobile-behavior-cases.json ios_app/Tests/HealthSyncTests/Fixtures/
cp datahub/contracts/mobile-behavior-cases.json android_app/contract/src/test/resources/fixtures/

datahub/.venv/bin/python datahub/scripts/mobile_parity.py check
datahub/.venv/bin/python datahub/scripts/mobile_parity.py report
datahub/.venv/bin/python datahub/scripts/mobile_parity.py verify \
  --output-dir /tmp/healthsave-paired-verification \
  --ios-destination 'platform=iOS Simulator,id=YOUR_SIMULATOR_ID'
```

Use the backend's Python 3.12/3.13 environment and Android's JDK 21 environment.
The output directory must be new and outside the three repositories. The runner
executes `make trust-fast`, Android `./gradlew check`, the full iOS test suite and
iOS localization preflight. It captures commands, exit codes, log hashes, source
revisions and contract hashes. Changes to source during the run invalidate it.
Runs with uncommitted changes are development evidence only.

`trust-fast` reports separately when the pinned OpenAPI/schema checks SKIP. A SKIP
does not validate those surfaces. If a change touches routes or schemas, run the
existing pinned Docker checks before release; do not substitute this mobile check.

Android retains its repository-local GitHub Actions check. iOS retains local test
and pre-push verification; this workflow adds no iOS GitHub Actions. The workspace
commands are required for paired checks because standalone CI lacks sibling repos.

## Release evidence

```sh
datahub/.venv/bin/python datahub/scripts/mobile_parity.py release-check \
  --evidence /tmp/healthsave-paired-verification/release-evidence.json
```

This check rejects open gaps, unclassified planned Android metrics, feature
differences, dirty source trees and missing or stale evidence. It does not publish
anything, replace store preflight, or grant operator release approval. Ordinary
debug builds and internal QA remain usable while parity is incomplete.

The bundle JSON uses this shape (placeholders must be replaced with real evidence):

```json
{
  "schema_version": 1,
  "revisions": {"ios": "commit", "android": "commit", "datahub": "commit"},
  "contracts": {
    "mobile-acceptance.json": "sha256",
    "mobile-behavior-cases.json": "sha256",
    "parity.json": "sha256"
  },
  "native_verification": {"path": "native-verification.json", "sha256": "sha256"},
  "checks": [{
    "acceptance_id": "export_csv",
    "platform": "android",
    "kind": "behavior",
    "result": "passed",
    "reviewer": "reviewer name",
    "observed_at": "2026-11-06T12:00:00Z",
    "artifact": {"path": "export-android-report.html", "sha256": "sha256"}
  }]
}
```

Include exactly one reviewed record for every scenario/platform/required kind.
Each visual record also declares `profiles` and `locales` covering the contract's
lists; its artifact should contain the corresponding labeled comparisons. Each
device record declares `device_kind: "physical"` and `device_os`. Artifacts and
native logs must remain inside the bundle and match their SHA256. Review and native
verification timestamps must be timezone-aware, not future-dated, and at most
30 days old. Candidate commits and contract hashes must match the current source.

The validator checks completeness and integrity of supplied evidence. It cannot
decide whether a screenshot truly matches or a reviewer actually performed an
action. Those remain explicit reviewer responsibilities. Never use a synthetic
test bundle as release evidence, and never store real health data in these reports.

## Present limits

The initial shared executable cases cover CSV escaping, exact mass conversion and
the Doctor Visit free-remake window. They do not cover the full app. The acceptance
matrix records the remaining export, insight, widget, pairing, medication, visual
and device gaps. Run `report` for current details rather than treating this document
as a completion claim. Full parity requires closing those gaps with actual code
and evidence.
