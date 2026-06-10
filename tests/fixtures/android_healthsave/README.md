# Android request corpus (golden payloads)

Mirror of the HealthSave Android app's real wire output. The Android app
(`../../../../android_app`, repo `umutkeltek/healthsave-android`) is the wire
source of truth for these requests: its `:contract` module emits them
deterministically via

```
./gradlew :contract:regenRequestCorpus
```

and the output is copied here byte-for-byte. Drift in either direction fails
`tests/contract/test_android_corpus_in_sync.py` (and the Android-side
`RequestCorpusTest.kt`). `tests/contract/test_android_requests_accepted.py`
replays every fixture through the live FastAPI handlers to prove the corpus is
not just pinned but ingestible.

Counterpart of `../apple_healthsave/` (iOS requests). Responses are NOT
duplicated per client: the server answers identically regardless of client, so
both apps mirror the single generated corpus in
`../apple_healthsave_responses/`.

The corpus is empty until the Android wire layer lands (P1 of the Android
plan); the sync tests self-skip while it is empty.
