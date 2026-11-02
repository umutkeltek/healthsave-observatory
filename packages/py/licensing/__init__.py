"""Observatory licences: an offline-verifiable, Ed25519-signed licence file.

A licence unlocks Observatory Care features (encrypted off-site and scheduled
backups, restore drills, update rollback). Verification happens on this machine
against the public key in :mod:`licensing.keys`; nothing is sent anywhere.
Free features never consult a licence.

Re-exports:

* :func:`current_license` - the installed licence, or ``None``.
* :func:`require_feature` - the installed licence if it allows a feature now,
  else a :class:`LicenseError` subclass with a sentence a person can act on.
* :func:`parse_license` - verify licence text (the file's contents).
* :func:`license_path` - where the installed file lives (next to config.yaml).
"""

from __future__ import annotations

from .verify import (
    FEATURE_BACKUP_OFFSITE,
    FEATURE_RESTORE_DRILL,
    FEATURE_UPDATE_ROLLBACK,
    GRACE_PERIOD,
    KNOWN_FEATURES,
    LICENSE_FILE_ENV,
    LICENSE_FILENAME,
    TIERS,
    FeatureNotLicensed,
    License,
    LicenseError,
    LicenseExpired,
    LicenseInvalid,
    LicenseNotFound,
    LicenseState,
    check_feature,
    current_license,
    embedded_public_key,
    license_path,
    load_license_file,
    parse_license,
    require_feature,
)

__all__ = [
    "FEATURE_BACKUP_OFFSITE",
    "FEATURE_RESTORE_DRILL",
    "FEATURE_UPDATE_ROLLBACK",
    "GRACE_PERIOD",
    "KNOWN_FEATURES",
    "LICENSE_FILENAME",
    "LICENSE_FILE_ENV",
    "TIERS",
    "FeatureNotLicensed",
    "License",
    "LicenseError",
    "LicenseExpired",
    "LicenseInvalid",
    "LicenseNotFound",
    "LicenseState",
    "check_feature",
    "current_license",
    "embedded_public_key",
    "license_path",
    "load_license_file",
    "parse_license",
    "require_feature",
]
