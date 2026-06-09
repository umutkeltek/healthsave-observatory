"""Authentication + secrets package.

Owns the small surface that source plugins need to store and use
third-party credentials without each plugin reinventing encryption,
token refresh, or audit trail.

Re-exports:

  * :class:`OAuthToken` — provider-agnostic decrypted token dataclass.
  * :data:`DEFAULT_OWNER_ID` — single-user sentinel UUID (matches the
    one in ``server.ingestion.owner``).
  * :func:`encrypt` / :func:`decrypt` — Fernet helpers used by the
    storage repo. Plugins should NOT import these directly; they
    interact with the token store, which encrypts on the boundary.
  * :func:`generate_key` — convenience for ``HDH_TOKEN_ENC_KEY``
    rotation runbooks.
"""

from __future__ import annotations

from .encryption import (
    ENV_KEY,
    TokenEncryptionError,
    decrypt,
    encrypt,
    generate_key,
)
from .keyring import (
    KEYRING_ENV,
    LEGACY_KEY_VERSION,
    Keyring,
    SealedSecret,
    active_key_version,
    last4,
    seal,
    unseal,
)
from .tokens import DEFAULT_OWNER_ID, OAuthToken

__all__ = [
    "DEFAULT_OWNER_ID",
    "ENV_KEY",
    "KEYRING_ENV",
    "LEGACY_KEY_VERSION",
    "Keyring",
    "OAuthToken",
    "SealedSecret",
    "TokenEncryptionError",
    "active_key_version",
    "decrypt",
    "encrypt",
    "generate_key",
    "last4",
    "seal",
    "unseal",
]
