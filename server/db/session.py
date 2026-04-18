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

engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session
