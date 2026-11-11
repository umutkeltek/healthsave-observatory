"""Optional request identity for safely retrying private document uploads."""

from uuid import UUID, uuid4

from fastapi import HTTPException, Request


def upload_id(request: Request) -> UUID:
    value = request.headers.get("x-upload-id")
    if value is None:
        return uuid4()
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "X-Upload-ID must be a UUID reused only for this upload.") from exc


def verify_retry(row: dict | None, **expected) -> None:
    if row is None or any(row.get(key) != value for key, value in expected.items()):
        raise HTTPException(
            409,
            "This upload ID was already used with different content or options. "
            "Start a new upload.",
        )
