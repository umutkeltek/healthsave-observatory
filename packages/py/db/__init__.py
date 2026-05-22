"""Database utilities used outside the request lifecycle.

Currently exposes :mod:`db.migrate` — the migration runner the Compose
``migrate`` service invokes before long-lived app processes start, so a
fresh ``docker compose up`` brings every datahub install to the latest
schema without manual psql steps.

This package is intentionally tiny. SQLAlchemy session machinery for
the API request path lives in ``server.db.session``; this package is
for one-shot bootstrap concerns that do not want or need the request-
session scaffolding.
"""
