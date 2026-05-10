"""Runtime-state primitives — for things-that-run.

Phase 5A moved the data-access layer out: ``runtime.runs`` is now
``storage.timescale.runs``. ``runtime`` keeps its name for future
*runtime behaviour* (state machines, schedulers, agent runtime control
loops) — the layer between data access and process glue.

Future (per the v2 plan):
- ``runtime.agents`` — agent runtime control loop (lease, retry, cancel).
- ``runtime.events`` — outbox dispatcher + stream projections.
"""
