import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from storage.document_pages import decode_cursor, next_cursor


def test_cursor_pins_both_timestamp_and_id_and_uses_the_last_visible_row():
    rows = [{"created_at": datetime(2026, 1, 1, tzinfo=UTC), "id": uuid4()} for _ in range(101)]
    assert decode_cursor(next_cursor(rows)) == (rows[99]["created_at"], rows[99]["id"])
    assert next_cursor(rows[:100]) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "nonsense",
        "a" * 201,
        *[
            base64.urlsafe_b64encode(json.dumps(x).encode()).decode()
            for x in [
                None,
                [],
                [12, 13],
                ["2026-01-01", str(uuid4())],
                ["0001-01-01T00:00:00+14:00", str(uuid4())],
            ]
        ],
    ],
)
def test_invalid_cursor_rejects_without_database_access(value):
    with pytest.raises(ValueError, match="cursor"):
        decode_cursor(value)
