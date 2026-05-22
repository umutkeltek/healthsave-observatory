"""Provider-agnostic OAuth token data model.

The dataclass holds *decrypted* secrets. Encryption is applied at the
storage boundary in :mod:`storage.timescale.oauth_tokens`, so plugins
that read or write tokens via the repo see plaintext and never touch
ciphertext directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

# Mirrors server.ingestion.owner.DEFAULT_OWNER_ID. Duplicated here
# rather than imported to keep the auth package free of any
# server/* dependency — it must work in worker, agents, and plugin
# processes that may not load server.
DEFAULT_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass(frozen=True, slots=True)
class OAuthToken:
    """One row in ``oauth_tokens`` after decryption.

    ``access_token`` and ``refresh_token`` carry secrets in plaintext;
    treat instances as sensitive and avoid logging them.
    """

    owner_id: UUID
    provider: str
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def is_expired(self, *, now: datetime | None = None, leeway_seconds: int = 60) -> bool:
        """Return True iff the token has expired (with a small refresh-ahead leeway).

        ``leeway_seconds`` deliberately defaults to 60 so the poll loop
        refreshes BEFORE the provider returns 401. Pick a larger value
        for sources where token refresh is rate-limited or expensive.
        """
        if self.expires_at is None:
            return False
        clock = now or datetime.now(UTC)
        return (self.expires_at - clock).total_seconds() < leeway_seconds
