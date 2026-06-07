"""Async SQLAlchemy engine and FastAPI session dependency.

Single source of truth for the database connection. All routers and the
analysis engine reuse this engine + sessionmaker.
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://healthsave:changeme@db:5432/healthsave",
)


def _engine_kwargs() -> dict:
    """PERFORMANCE-002: resilient async-engine pool config.

    - ``pool_pre_ping`` detects connections dropped by the DB / pooler / firewall
      during idle, so the first query after a quiet period doesn't fail with
      "server closed the connection unexpectedly".
    - ``pool_recycle`` proactively retires connections before a typical idle
      timeout.
    - ``pool_timeout`` bounds how long a request waits for a free connection
      (the small pool + per-row ingest can otherwise queue requests forever).
    - ``statement_timeout`` is OPT-IN (DB_STATEMENT_TIMEOUT_MS): a server-side
      cap on runaway queries. Off by default so legitimate slow queries (large
      exports, aggregate refreshes) are never killed unless an operator opts in.

    All knobs are env-tunable; the pool size/overflow defaults match the prior
    behaviour, so this is a non-breaking hardening change.
    """
    kwargs: dict = {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")),
    }
    statement_timeout_ms = os.getenv("DB_STATEMENT_TIMEOUT_MS", "").strip()
    if statement_timeout_ms:
        # asyncpg applies Postgres GUCs per connection via server_settings.
        kwargs["connect_args"] = {"server_settings": {"statement_timeout": statement_timeout_ms}}
    return kwargs


engine = create_async_engine(DATABASE_URL, **_engine_kwargs())
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session
