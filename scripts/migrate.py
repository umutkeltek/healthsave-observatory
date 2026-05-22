"""CLI wrapper around :func:`db.migrate.apply_migrations`.

Run from a shell or invoke from the Compose ``migrate`` service.
Reads ``DATABASE_URL`` from the environment and applies every
``db/migrations/*.sql`` file that the tracking table does not yet
list as applied.

Exit codes:

  0  every migration applied successfully (or no work to do)
  1  required env var missing
  2  one migration failed; the transaction was rolled back and
     re-running is safe
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path


def _migrations_dir() -> Path:
    """Walk up from scripts/ to the repo root, then to db/migrations.

    The Docker image copies these into /app/db/migrations; the layout
    lookup is the same in both worlds.
    """
    here = Path(__file__).resolve()
    return here.parent.parent / "db" / "migrations"


async def _run() -> int:
    from db.migrate import apply_migrations

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 1

    migrations_dir = _migrations_dir()
    try:
        result = await apply_migrations(db_url, migrations_dir)
    except Exception as e:
        print(f"error: migration failed: {e}", file=sys.stderr)
        return 2

    if result.applied:
        print(f"applied {len(result.applied)} migration(s):")
        for name in result.applied:
            print(f"  + {name}")
    else:
        print("schema already up-to-date")
    if result.skipped:
        print(f"({len(result.skipped)} migration(s) already tracked)")
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":  # pragma: no cover
    main()
