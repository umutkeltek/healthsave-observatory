"""Storage ports + implementations.

The split:
- ``storage.ports`` — Protocol contracts. The shape every storage-backed
  concern conforms to. Application code (``apps/api``, ``apps/worker``,
  ``apps/agents`` later) imports from here.
- ``storage.timescale`` — concrete TimescaleDB implementations of those
  ports. The only place sqlalchemy lives outside ``apps/api/server/db``
  (which still owns the engine + session bootstrap for v1.x).

Goal (Phase 5D end state): ``rg "import sqlalchemy" packages/py/ apps/``
returns zero hits outside ``packages/py/storage/timescale``. We are not
there yet — Phase 5A introduces the pattern with one port (RunRepository);
Phase 5B-D migrates the rest.

Why ports: TimescaleDB is the v1 implementation. v2.x should be able to
swap to DuckDB-local, ClickHouse, a hosted warehouse, or in-memory stubs
for tests without touching app code. The ports define the swappable seam.
"""
