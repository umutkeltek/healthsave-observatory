# Golden HealthSave iOS response corpus

**Generated files — do not hand-edit.** Regenerate with
`make regen-response-corpus` (or
`python -m scripts.generate_ios_response_corpus`).

These are the responses the server's real handlers return for the five
endpoints the shipped HealthSave iOS binary calls, produced in-process
with fixed inputs so they are byte-reproducible. Each file is an
envelope `{"endpoint", "method", "status", "body"}`.

They are the response-direction counterpart of the request corpus in
`../apple_healthsave/` and are mirrored byte-for-byte into
`ios_app/Tests/HealthSyncTests/Fixtures/Responses/`, where the iOS
suite (`BackendResponseCorpusTests.swift`) decodes them through the
app's real parsing paths.

Drift gates:

- `scripts/generate_ios_response_corpus.py --check` (datahub CI) — a
  handler change that alters any response shape goes red here first.
- `tests/contract/test_ios_response_corpus_in_sync.py` (product
  workspace) — fails until the iOS mirror matches this corpus.

After regenerating: copy the JSONs into the iOS mirror and run the iOS
`BackendResponseCorpusTests` before shipping the server change.
