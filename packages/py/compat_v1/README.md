# compat_v1

The v1 compatibility capsule. Everything in this package is **frozen
for v1 wire compatibility**.

## What lives here

| File | Contents |
|------|----------|
| `__init__.py` | `V1_ROUTES_FROZEN` and `IOS_FROZEN_ROUTES` — the route inventories pinned by the contract tests |
| `models/batch.py` | `BatchPayload` — `POST /api/apple/batch` request shape |
| `models/insights.py` | `*Response` and `Trigger*` models — `GET/POST /api/insights/*` shapes |

## Hard rule

A change to anything in this package is a v1 contract change. CI
fails the build via:

- `tests/contract/api_v1/test_v1_contract.py` — full OpenAPI lock match
- `tests/contract/api_v1/test_v1_ios_contract.py` — iOS-narrow subset
- `python -m scripts.generate_v1_lock --check` (CI step)

## When v2 arrives

`packages/py/contracts/` will hold the v2 canonical schemas. The
boundary between v1 and v2 is structural: anything imported from
`compat_v1` is v1-frozen; anything from `contracts` is v2.

The two coexist forever — v1 clients are not deprecated, just
contracted into one corner of the codebase.
