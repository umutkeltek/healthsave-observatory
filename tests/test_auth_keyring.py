"""Tests for the key-versioned Fernet keyring in ``auth.keyring`` — ADR-0003 D3.

Pins the rotation contract:

  * seal → unseal round-trips and tags the head version,
  * a ciphertext sealed by an old head still opens after the head rotates
    (the whole point of the ring), while new seals use the new head,
  * the legacy ``HDH_TOKEN_ENC_KEY`` is adopted as a one-entry ``v0`` ring
    AND a ciphertext sealed by ``auth.encrypt`` opens through that ring
    (zero-config back-compat),
  * ``HDH_KEYRING`` takes precedence over the legacy key,
  * tamper / wrong-key surfaces as :class:`TokenEncryptionError`,
  * malformed ``HDH_KEYRING`` fails loud, never silently empty.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import (  # noqa: E402
    ENV_KEY,
    TokenEncryptionError,
    active_key_version,
    encrypt,
    generate_key,
    last4,
    seal,
    unseal,
)
from auth.keyring import (  # noqa: E402
    KEYRING_ENV,
    LEGACY_KEY_VERSION,
    _build_keyring,
    _keyring_from_env,
    _parse_keyring_env,
)


def _ring(*pairs: tuple[str, str]):
    """Build an explicit ring (head first) so tests never touch process env."""
    return _build_keyring(list(pairs))


def test_seal_unseal_round_trips_and_tags_head_version():
    ring = _ring(("v1", generate_key()))
    for plaintext in ("", "sk-deepseek-123", "unicode → 漢字 ✨", "long " * 1000):
        sealed = seal(plaintext, ring=ring)
        assert sealed.key_version == "v1"
        assert isinstance(sealed.ciphertext, bytes)
        assert unseal(sealed.ciphertext, ring=ring) == plaintext


def test_active_key_version_is_the_head():
    ring = _ring(("2026q2", generate_key()), ("2026q1", generate_key()))
    assert active_key_version(ring=ring) == "2026q2"


def test_old_ciphertext_opens_after_head_rotation():
    old_key, new_key = generate_key(), generate_key()
    old_ring = _ring(("v1", old_key))
    sealed = seal("rotate-me", ring=old_ring)
    assert sealed.key_version == "v1"

    # Operator rotates: new head v2, old v1 kept trailing (decrypt-only).
    rotated = _ring(("v2", new_key), ("v1", old_key))
    assert unseal(sealed.ciphertext, ring=rotated) == "rotate-me"  # old ct still opens
    assert seal("fresh", ring=rotated).key_version == "v2"  # new seals use new head


def test_unseal_ignores_advisory_key_version():
    ring = _ring(("v2", generate_key()), ("v1", generate_key()))
    sealed = seal("hi", ring=ring)
    # A stale/wrong version hint must not break unseal — MultiFernet finds it.
    assert unseal(sealed.ciphertext, key_version="bogus", ring=ring) == "hi"


def test_tampered_ciphertext_raises():
    ring = _ring(("v1", generate_key()))
    ct = bytearray(seal("important", ring=ring).ciphertext)
    ct[len(ct) // 2] ^= 0x01
    with pytest.raises(TokenEncryptionError):
        unseal(bytes(ct), ring=ring)


def test_unknown_key_raises():
    sealed = seal("secret", ring=_ring(("v1", generate_key())))
    other = _ring(("v9", generate_key()))
    with pytest.raises(TokenEncryptionError):
        unseal(sealed.ciphertext, ring=other)


def test_invalid_fernet_key_in_ring_raises():
    with pytest.raises(TokenEncryptionError):
        _ring(("v1", "not-a-real-fernet-key"))


# --- HDH_KEYRING parsing ---------------------------------------------------


def test_parse_keyring_env_ordered_pairs():
    a, b = generate_key(), generate_key()
    assert _parse_keyring_env(f"v2:{a}, v1:{b}") == [("v2", a), ("v1", b)]


def test_parse_keyring_env_missing_colon_raises():
    with pytest.raises(TokenEncryptionError):
        _parse_keyring_env(generate_key())  # a bare key, no "id:" prefix


def test_parse_keyring_env_duplicate_versions_raises():
    a, b = generate_key(), generate_key()
    with pytest.raises(TokenEncryptionError):
        _parse_keyring_env(f"v1:{a},v1:{b}")


def test_parse_keyring_env_empty_raises():
    with pytest.raises(TokenEncryptionError):
        _parse_keyring_env("  ,  ")


# --- env resolution (HDH_KEYRING vs legacy HDH_TOKEN_ENC_KEY) --------------


def test_keyring_env_takes_precedence_over_legacy(monkeypatch):
    ring_key, legacy_key = generate_key(), generate_key()
    monkeypatch.setenv(KEYRING_ENV, f"v3:{ring_key}")
    monkeypatch.setenv(ENV_KEY, legacy_key)
    _keyring_from_env.cache_clear()
    try:
        assert active_key_version() == "v3"
        sealed = seal("env-routed")
        assert sealed.key_version == "v3"
        assert unseal(sealed.ciphertext) == "env-routed"
    finally:
        _keyring_from_env.cache_clear()


def test_legacy_key_adopted_as_v0_and_opens_auth_encrypt_ciphertext(monkeypatch):
    legacy_key = generate_key()
    monkeypatch.delenv(KEYRING_ENV, raising=False)
    monkeypatch.setenv(ENV_KEY, legacy_key)
    _keyring_from_env.cache_clear()
    try:
        # Legacy single key → one-entry "v0" ring.
        assert active_key_version() == LEGACY_KEY_VERSION
        # A ciphertext sealed by the OLD single-key helper still opens via the
        # ring (same underlying key) — the zero-config migration guarantee.
        legacy_ct = encrypt("from-oauth-tokens", key=legacy_key)
        assert unseal(legacy_ct) == "from-oauth-tokens"
    finally:
        _keyring_from_env.cache_clear()


def test_no_key_configured_raises(monkeypatch):
    monkeypatch.delenv(KEYRING_ENV, raising=False)
    monkeypatch.delenv(ENV_KEY, raising=False)
    _keyring_from_env.cache_clear()
    try:
        with pytest.raises(TokenEncryptionError) as exc:
            seal("anything")
        assert KEYRING_ENV in str(exc.value)
    finally:
        _keyring_from_env.cache_clear()


# --- display hint ----------------------------------------------------------


def test_last4_masks_all_but_tail():
    assert last4("sk-abcd1234") == "••••1234"
    assert last4("xy") == "••••"  # too short → no tail leaked
    assert last4("") == "••••"
