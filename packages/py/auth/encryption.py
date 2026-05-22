"""Fernet wrapper for at-rest encryption of OAuth tokens.

Key comes from env ``HDH_TOKEN_ENC_KEY``, which MUST be a URL-safe
base64-encoded 32-byte key — exactly what
``cryptography.fernet.Fernet.generate_key()`` produces. We deliberately
do NOT derive the key from a passphrase: Fernet keys are short, easy
to rotate, and Fernet handles AEAD properly without us reaching for
``PBKDF2`` and getting the iteration count wrong.

Rotation is out of scope for v1. When operationally needed, swap the
single ``Fernet`` for ``cryptography.fernet.MultiFernet`` with
``[new_key, old_key]`` — decrypts succeed against either, encrypts use
the head. After rewriting every row, drop the old key.
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

ENV_KEY = "HDH_TOKEN_ENC_KEY"


class TokenEncryptionError(Exception):
    """Raised when encryption or decryption fails (bad key, corrupt ciphertext)."""


@lru_cache(maxsize=1)
def _fernet_from_env() -> Fernet:
    raw = os.environ.get(ENV_KEY)
    if not raw:
        raise TokenEncryptionError(
            f"{ENV_KEY} not set — required for OAuth token encryption. "
            "Generate one with: python -c "
            "'from auth.encryption import generate_key; print(generate_key())'"
        )
    try:
        return Fernet(raw.encode())
    except Exception as e:
        raise TokenEncryptionError(f"{ENV_KEY} is not a valid Fernet key") from e


def _fernet(key: str | None) -> Fernet:
    """Return a Fernet for ``key`` or the cached env-derived one.

    Tests pass an explicit key to keep the cache from leaking state
    between cases.
    """
    if key is None:
        return _fernet_from_env()
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise TokenEncryptionError("provided key is not a valid Fernet key") from e


def encrypt(plaintext: str, *, key: str | None = None) -> bytes:
    """Encrypt a UTF-8 string. Returns ciphertext bytes for BYTEA storage."""
    return _fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes, *, key: str | None = None) -> str:
    """Decrypt BYTEA ciphertext. Raises :class:`TokenEncryptionError` on tamper / bad key."""
    try:
        return _fernet(key).decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise TokenEncryptionError("ciphertext failed authentication — tamper or wrong key") from e


def generate_key() -> str:
    """Return a fresh ``HDH_TOKEN_ENC_KEY`` value (URL-safe base64, 32 bytes)."""
    return Fernet.generate_key().decode()
