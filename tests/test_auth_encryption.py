"""Tests for the Fernet token-encryption helpers in ``packages/py/auth``.

The helpers are deliberately tiny — these tests pin the contract:

  * round-trip works for arbitrary UTF-8 strings,
  * a wrong key surfaces as :class:`TokenEncryptionError` (not a
    silent empty-string return),
  * tamper of even one byte is detected,
  * :func:`generate_key` produces a key that validates as a Fernet
    key.

Env-derived key handling (the production path) is covered by
mutating os.environ in one focused test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import (  # noqa: E402
    ENV_KEY,
    TokenEncryptionError,
    decrypt,
    encrypt,
    generate_key,
)
from auth.encryption import _fernet_from_env  # noqa: E402


def test_generate_key_produces_valid_fernet_key():
    key = generate_key()
    assert isinstance(key, str)
    # Round-trip with the generated key proves it's a valid Fernet key.
    ct = encrypt("hello", key=key)
    assert decrypt(ct, key=key) == "hello"


def test_encrypt_decrypt_round_trip_with_explicit_key():
    key = generate_key()
    for plaintext in ("", "hello", "with unicode → 漢字 ✨", "long " * 1000):
        ct = encrypt(plaintext, key=key)
        assert isinstance(ct, bytes)
        assert decrypt(ct, key=key) == plaintext


def test_decrypt_with_wrong_key_raises_token_encryption_error():
    ct = encrypt("secret", key=generate_key())
    with pytest.raises(TokenEncryptionError):
        decrypt(ct, key=generate_key())


def test_decrypt_tampered_ciphertext_raises():
    key = generate_key()
    ct = bytearray(encrypt("important", key=key))
    # Flip a byte in the middle of the ciphertext.
    ct[len(ct) // 2] ^= 0x01
    with pytest.raises(TokenEncryptionError):
        decrypt(bytes(ct), key=key)


def test_missing_env_key_raises_with_actionable_message(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    _fernet_from_env.cache_clear()
    with pytest.raises(TokenEncryptionError) as excinfo:
        encrypt("anything")
    assert ENV_KEY in str(excinfo.value)
    assert "generate_key" in str(excinfo.value)


def test_invalid_env_key_raises():
    import os

    os.environ[ENV_KEY] = "not-a-real-fernet-key"
    _fernet_from_env.cache_clear()
    try:
        with pytest.raises(TokenEncryptionError):
            encrypt("anything")
    finally:
        del os.environ[ENV_KEY]
        _fernet_from_env.cache_clear()


def test_env_key_used_when_no_explicit_key(monkeypatch):
    key = generate_key()
    monkeypatch.setenv(ENV_KEY, key)
    _fernet_from_env.cache_clear()
    try:
        ct = encrypt("via env")
        assert decrypt(ct) == "via env"
    finally:
        _fernet_from_env.cache_clear()
