"""Key-versioned Fernet keyring for at-rest secrets — ADR-0003 D3.

Extends the single-key :mod:`auth.encryption` to a rotation-capable ring.
A secret is *sealed* with the ring's **head** key and tagged with that
key's version id; *unsealing* tries every key in the ring (via
``cryptography.fernet.MultiFernet``), so a ciphertext sealed by an older
head still opens after the head rotates. Re-sealing rows with the new head
— then dropping the retired key once every row is migrated — is an operator
runbook, not an automatic step.

Why a separate ring instead of touching :func:`auth.encrypt`: the existing
``oauth_tokens`` ciphertext is sealed by that single-key helper, and the
intelligence credential store (migration 017) wants versioned rotation
without a flag day. This module adds the versioned path; ``auth.encrypt``
stays untouched for back-compat.

Keyring source (first that is set wins):

  * ``HDH_KEYRING`` — the explicit ring, ``"id:key,id:key,..."`` where the
    FIRST pair is the head used for new seals. Each ``key`` is a URL-safe
    base64 Fernet key (see :func:`auth.generate_key`); ``id`` is any short
    label with no ``:`` or ``,`` (e.g. ``v1``, ``2026q2``).
  * ``HDH_TOKEN_ENC_KEY`` — the legacy single key, adopted as a one-entry
    ring with version id ``"v0"``. This means a deploy that only set the
    legacy key keeps working with zero config, and a credential sealed
    today still opens after the operator later introduces ``HDH_KEYRING``
    with ``v0`` kept as a trailing (decrypt-only) entry.

The version id is stored alongside the ciphertext (``llm_credentials.
key_version``) purely for audit + rotation detection — unsealing does not
need it because MultiFernet finds the right key. A row whose ``key_version``
≠ :func:`active_key_version` is a re-seal candidate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .encryption import ENV_KEY, TokenEncryptionError

# Version id assigned to the legacy single key when no explicit ring is set.
LEGACY_KEY_VERSION = "v0"

# Env var holding the explicit, ordered ring (head first).
KEYRING_ENV = "HDH_KEYRING"


@dataclass(frozen=True)
class SealedSecret:
    """A ciphertext plus the version id of the key that sealed it."""

    ciphertext: bytes
    key_version: str


@dataclass(frozen=True)
class Keyring:
    """An ordered set of Fernet keys: the head seals, every key unseals.

    ``head_version`` names the key used for new :meth:`seal` calls.
    ``_fernet`` is a :class:`MultiFernet` built head-first, so encrypt uses
    the head and decrypt tries each key in turn.
    """

    head_version: str
    _fernet: MultiFernet

    def seal(self, plaintext: str) -> SealedSecret:
        """Encrypt ``plaintext`` with the head key; tag with its version."""
        return SealedSecret(
            ciphertext=self._fernet.encrypt(plaintext.encode("utf-8")),
            key_version=self.head_version,
        )

    def unseal(self, ciphertext: bytes, *, key_version: str | None = None) -> str:
        """Decrypt against any key in the ring.

        ``key_version`` is advisory (audit / rotation hints) — MultiFernet
        locates the right key regardless. Raises
        :class:`~auth.TokenEncryptionError` on tamper or an unknown key.
        """
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise TokenEncryptionError(
                "ciphertext failed authentication — tamper, or no ring key matches"
            ) from exc


def _build_keyring(entries: list[tuple[str, str]]) -> Keyring:
    """Build a :class:`Keyring` from ordered ``(version, key)`` pairs (head first)."""
    if not entries:
        raise TokenEncryptionError(
            f"no encryption key configured — set {KEYRING_ENV} (id:key,...) or {ENV_KEY}"
        )
    fernets: list[Fernet] = []
    for version, key in entries:
        try:
            fernets.append(Fernet(key.encode()))
        except Exception as exc:  # noqa: BLE001 - normalise to our error type
            raise TokenEncryptionError(
                f"keyring entry {version!r} is not a valid Fernet key"
            ) from exc
    head_version = entries[0][0]
    return Keyring(head_version=head_version, _fernet=MultiFernet(fernets))


def _parse_keyring_env(raw: str) -> list[tuple[str, str]]:
    """Parse ``HDH_KEYRING`` (``id:key,id:key``) into ordered pairs.

    Fernet keys are URL-safe base64 (``A-Za-z0-9-_=``) and never contain
    ``:`` or ``,``, so those split cleanly. The first pair is the head.
    """
    entries: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        pair = chunk.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise TokenEncryptionError(
                f"{KEYRING_ENV} entry {pair!r} must be 'id:key' (missing ':')"
            )
        version, key = pair.split(":", 1)
        version, key = version.strip(), key.strip()
        if not version or not key:
            raise TokenEncryptionError(f"{KEYRING_ENV} entry {pair!r} has an empty id or key")
        entries.append((version, key))
    if not entries:
        raise TokenEncryptionError(f"{KEYRING_ENV} is set but empty")
    versions = [v for v, _ in entries]
    if len(set(versions)) != len(versions):
        raise TokenEncryptionError(f"{KEYRING_ENV} has duplicate version ids: {versions}")
    return entries


@lru_cache(maxsize=1)
def _keyring_from_env() -> Keyring:
    """The process keyring, derived from env (cached; tests clear via ``cache_clear``)."""
    raw = os.environ.get(KEYRING_ENV)
    if raw:
        return _build_keyring(_parse_keyring_env(raw))
    legacy = os.environ.get(ENV_KEY)
    if legacy:
        return _build_keyring([(LEGACY_KEY_VERSION, legacy)])
    raise TokenEncryptionError(
        f"no encryption key configured — set {KEYRING_ENV} (id:key,...) or {ENV_KEY}. "
        "Generate a key with: python -c "
        "'from auth import generate_key; print(generate_key())'"
    )


def _resolve(ring: Keyring | None) -> Keyring:
    return ring if ring is not None else _keyring_from_env()


def seal(plaintext: str, *, ring: Keyring | None = None) -> SealedSecret:
    """Seal a secret with the head key; returns ciphertext + its version id."""
    return _resolve(ring).seal(plaintext)


def unseal(
    ciphertext: bytes, *, key_version: str | None = None, ring: Keyring | None = None
) -> str:
    """Unseal a ciphertext against the ring (any key); ``key_version`` is advisory."""
    return _resolve(ring).unseal(ciphertext, key_version=key_version)


def active_key_version(*, ring: Keyring | None = None) -> str:
    """The version id new seals use — i.e. the head key's id."""
    return _resolve(ring).head_version


def last4(secret: str) -> str:
    """A non-secret display hint: the last 4 chars, or ``"••••"`` if too short.

    Used for ``llm_credentials.key_last4`` so a UI can show ``"••••abcd"``
    without ever returning the key. Never include more than the tail.
    """
    tail = secret[-4:] if len(secret) >= 4 else ""
    return f"••••{tail}" if tail else "••••"
