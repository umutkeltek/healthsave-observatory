"""Parse and verify an Observatory licence file, fully offline.

The file format is shared with the billing service that signs licences::

    base64url(payload) + "." + base64url(signature)

``payload`` is canonical JSON (keys sorted, no whitespace)::

    {"email_sha256":"<hex>","exp":"<RFC3339 UTC>","features":[...],
     "iat":"<RFC3339 UTC>","nonce":"<base64url>","seats":1,
     "sub":"<customer id>","tier":"care|hosted|teams","v":1}

``signature`` is Ed25519 over the exact payload bytes. Checking a licence needs
only the public key in :mod:`licensing.keys`. Nothing in this package opens a
network connection: a licence is never reported, refreshed or revoked online.
Renewal is a new file. After ``exp`` a licence keeps working for a 14-day grace
period, then its features stop; free features never depend on a licence.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import keys

LICENSE_FILENAME = "healthsave.license"
LICENSE_FILE_ENV = "HEALTHSAVE_LICENSE_FILE"
GRACE_PERIOD = timedelta(days=14)
FORMAT_VERSION = 1
TIERS = frozenset({"care", "hosted", "teams"})

# Feature names the code gates on. A licence may carry names this build does
# not know yet (a newer feature); they are kept and simply never asked for.
FEATURE_BACKUP_OFFSITE = "care.backup.offsite"
FEATURE_RESTORE_DRILL = "care.restore.drill"
FEATURE_UPDATE_ROLLBACK = "care.update.rollback"
KNOWN_FEATURES = frozenset({FEATURE_BACKUP_OFFSITE, FEATURE_RESTORE_DRILL, FEATURE_UPDATE_ROLLBACK})

_B64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_SIGNATURE_BYTES = 64


class LicenseError(Exception):
    """Base class. ``str(error)`` is a sentence a person can act on."""


class LicenseNotFound(LicenseError):
    """No licence file is installed."""


class LicenseInvalid(LicenseError):
    """The file is malformed, or its signature does not match its contents."""


class LicenseExpired(LicenseError):
    """The licence expired and its grace period is over."""

    def __init__(self, message: str, license: License) -> None:
        super().__init__(message)
        self.license = license


class FeatureNotLicensed(LicenseError):
    """The licence is valid but does not include the requested feature."""

    def __init__(self, message: str, license: License, feature: str) -> None:
        super().__init__(message)
        self.license = license
        self.feature = feature


class LicenseState(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"


@dataclass(frozen=True)
class License:
    """A licence whose signature has been verified."""

    tier: str
    sub: str
    email_sha256: str
    seats: int
    features: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    nonce: str
    version: int = FORMAT_VERSION

    @property
    def grace_ends_at(self) -> datetime:
        return self.expires_at + GRACE_PERIOD

    def state(self, now: datetime | None = None) -> LicenseState:
        moment = _now() if now is None else _as_utc(now)
        if moment <= self.expires_at:
            return LicenseState.ACTIVE
        if moment <= self.grace_ends_at:
            return LicenseState.GRACE
        return LicenseState.EXPIRED

    def includes(self, feature: str) -> bool:
        return feature in self.features


def embedded_public_key() -> Ed25519PublicKey:
    """The verification key compiled into this build."""
    return Ed25519PublicKey.from_public_bytes(_b64url_decode(keys.PUBLIC_KEY_B64URL, "public key"))


def parse_license(text: str, *, public_key: Ed25519PublicKey | None = None) -> License:
    """Verify ``text`` (the licence file's contents) and return the licence.

    Raises :class:`LicenseInvalid` if the file is malformed or the signature
    does not match. Expiry is not checked here; see :meth:`License.state`.
    """
    token = text.strip()
    payload_part, dot, signature_part = token.partition(".")
    if not dot or not payload_part or not signature_part or "." in signature_part:
        raise LicenseInvalid("This is not a HealthSave licence file (expected two parts).")
    payload = _b64url_decode(payload_part, "payload")
    signature = _b64url_decode(signature_part, "signature")
    if len(signature) != _SIGNATURE_BYTES:
        raise LicenseInvalid("This licence file is damaged (its signature has the wrong length).")
    key = embedded_public_key() if public_key is None else public_key
    try:
        key.verify(signature, payload)
    except InvalidSignature:
        raise LicenseInvalid(
            "This licence file was changed after it was issued, or was not issued "
            "for HealthSave Observatory (the signature does not match)."
        ) from None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LicenseInvalid("This licence file is damaged (its payload is not JSON).") from None
    if not isinstance(data, dict):
        raise LicenseInvalid("This licence file is damaged (its payload is not an object).")
    return _license_from_payload(data)


def license_path() -> Path:
    """Where the installed licence lives: next to ``config.yaml``.

    ``HEALTHSAVE_LICENSE_FILE`` wins when set. Otherwise the file sits in the
    directory of ``ANALYSIS_CONFIG`` (the server's config.yaml path) when that is
    set, else in the working directory: the ``healthsave`` CLI runs from the
    checkout that holds config.yaml, and the container's working directory is
    /app, where config.yaml is mounted.
    """
    explicit = os.environ.get(LICENSE_FILE_ENV)
    if explicit:
        return Path(explicit)
    config = os.environ.get("ANALYSIS_CONFIG")
    base = Path(config).parent if config else Path.cwd()
    return base / LICENSE_FILENAME


def load_license_file(path: Path | str) -> License:
    """Read and verify a licence file. Raises :class:`LicenseNotFound` if absent."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LicenseNotFound(f"No licence file at {file}.") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise LicenseInvalid(f"Could not read the licence file at {file}: {exc}") from None
    return parse_license(text)


def current_license(path: Path | str | None = None) -> License | None:
    """The installed licence, or ``None`` when no licence file is installed.

    Raises :class:`LicenseInvalid` when a file is installed but does not verify.
    An expired licence is still returned; check :meth:`License.state`.
    """
    try:
        return load_license_file(license_path() if path is None else path)
    except LicenseNotFound:
        return None


def require_feature(
    feature: str, *, path: Path | str | None = None, now: datetime | None = None
) -> License:
    """Return the installed licence if it allows ``feature`` right now.

    Raises :class:`LicenseNotFound`, :class:`LicenseInvalid`,
    :class:`LicenseExpired` or :class:`FeatureNotLicensed`; all are
    :class:`LicenseError`. During the grace period the feature is allowed.
    """
    if feature not in KNOWN_FEATURES:
        raise ValueError(f"unknown licence feature {feature!r}")
    license = load_license_file(license_path() if path is None else path)
    return check_feature(license, feature, now=now)


def check_feature(license: License, feature: str, *, now: datetime | None = None) -> License:
    """Apply the expiry and feature rules to an already verified licence."""
    if license.state(now) is LicenseState.EXPIRED:
        raise LicenseExpired(
            f"The Observatory {license.tier} licence expired on {_day(license.expires_at)} "
            f"and its 14-day grace period ended on {_day(license.grace_ends_at)}. "
            "Renew it to use this feature again; free features keep working.",
            license,
        )
    if not license.includes(feature):
        raise FeatureNotLicensed(
            f"The installed {license.tier} licence does not include {feature}.",
            license,
            feature,
        )
    return license


def _license_from_payload(data: dict[str, Any]) -> License:
    version = data.get("v")
    if type(version) is not int or version != FORMAT_VERSION:
        raise LicenseInvalid(
            f"This licence file uses format {version!r}; this Observatory reads format "
            f"{FORMAT_VERSION}. Update Observatory, or ask for a new file."
        )
    tier = data.get("tier")
    if tier not in TIERS:
        raise LicenseInvalid(f"This licence file names an unknown tier {tier!r}.")
    sub = data.get("sub")
    if not isinstance(sub, str) or not sub:
        raise LicenseInvalid("This licence file has no customer id.")
    email_sha256 = data.get("email_sha256")
    if not isinstance(email_sha256, str) or not _SHA256_HEX.fullmatch(email_sha256.lower()):
        raise LicenseInvalid("This licence file has a malformed email hash.")
    seats = data.get("seats")
    if type(seats) is not int or seats < 1:
        raise LicenseInvalid("This licence file has a malformed seat count.")
    features = data.get("features")
    if not isinstance(features, list) or not all(isinstance(f, str) and f for f in features):
        raise LicenseInvalid("This licence file has a malformed feature list.")
    nonce = data.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise LicenseInvalid("This licence file has no nonce.")
    issued_at = _parse_time(data.get("iat"), "iat")
    expires_at = _parse_time(data.get("exp"), "exp")
    if expires_at <= issued_at:
        raise LicenseInvalid("This licence file expires before it was issued.")
    return License(
        tier=tier,
        sub=sub,
        email_sha256=email_sha256.lower(),
        seats=seats,
        features=tuple(features),
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce,
        version=version,
    )


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise LicenseInvalid(f"This licence file has no {field} time.")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise LicenseInvalid(f"This licence file has a malformed {field} time.") from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise LicenseInvalid(f"This licence file's {field} time has no time zone.")
    return moment.astimezone(UTC)


def _b64url_decode(part: str, what: str) -> bytes:
    if not _B64URL.fullmatch(part):
        raise LicenseInvalid(f"This licence file is damaged (its {what} is not base64url).")
    bare = part.rstrip("=")
    try:
        return base64.urlsafe_b64decode(bare + "=" * (-len(bare) % 4))
    except (binascii.Error, ValueError):
        raise LicenseInvalid(
            f"This licence file is damaged (its {what} is not base64url)."
        ) from None


def b64url_encode(data: bytes) -> str:
    """base64url without padding, the form licence files use."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical_payload(data: dict[str, Any]) -> bytes:
    """The exact bytes a licence signature covers: sorted keys, no whitespace."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return moment.astimezone(UTC)


def _day(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")
