"""Runtime-state primitives — the data layer for things-that-run.

Currently:
- ``runtime.runs`` — pipeline_runs ledger (claim/mark/fetch).

Future (per the v2 plan):
- ``runtime.agents`` — agent run ledger, observations, action proposals.
- ``runtime.events`` — outbox + projections.

The shape here is data-access, not contract types — those live in
``packages/py/contracts``. The two are complementary: contracts describe
what shapes flow over the wire; runtime describes how they get persisted.
"""
