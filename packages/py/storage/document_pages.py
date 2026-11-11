"""Bounded keyset pagination for owner-scoped private document histories."""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

PAGE_SIZE = 100


def decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        if not value or len(value) > 200:
            raise ValueError
        raw = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(item, str) for item in raw)
        ):
            raise ValueError
        created, identifier = datetime.fromisoformat(raw[0]), UUID(raw[1])
        if created.tzinfo is None:
            raise ValueError
        return created.astimezone(UTC), identifier
    except (ValueError, TypeError, OverflowError, binascii.Error) as exc:
        raise ValueError("Invalid document-history cursor. Reload the document list.") from exc


def next_cursor(rows: list[dict]) -> str | None:
    if len(rows) <= PAGE_SIZE:
        return None
    row = rows[PAGE_SIZE - 1]
    payload = json.dumps([row["created_at"].isoformat(), str(row["id"])], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()
