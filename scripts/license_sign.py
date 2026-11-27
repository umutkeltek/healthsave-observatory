"""Sign an Observatory licence payload.

Usage:
    HEALTHSAVE_LICENSE_SIGNING_KEY=/path/to/key.pem \\
        python scripts/license_sign.py payload.json [--days 365] [--out FILE]
    python scripts/license_sign.py payload.json --keychain [--days 365] [--out FILE]

The private key (PKCS8 PEM) comes from the file named by
``HEALTHSAVE_LICENSE_SIGNING_KEY``, or with ``--keychain`` from the macOS login
Keychain item the billing service uses (service ``healthsave-licence-signing-key``,
account ``ed25519-pkcs8-pem``). The key is never printed.

``payload.json`` holds the licence fields (``-`` reads stdin). Missing ``v``,
``iat`` and ``nonce`` are filled in (1, now, 16 random bytes); a missing ``exp``
needs ``--days``. The payload is checked with the same parser Observatory uses,
signed over its canonical JSON (sorted keys, no whitespace), verified, and the
licence file text is written to ``--out`` or stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages" / "py") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "py"))

from licensing.verify import (  # noqa: E402
    FORMAT_VERSION,
    LicenseInvalid,
    b64url_encode,
    canonical_payload,
    embedded_public_key,
    parse_license,
)

KEY_PATH_ENV = "HEALTHSAVE_LICENSE_SIGNING_KEY"
KEYCHAIN_SERVICE = "healthsave-licence-signing-key"
KEYCHAIN_ACCOUNT = "ed25519-pkcs8-pem"


def complete_payload(
    payload: dict[str, Any], *, now: datetime | None = None, days: int | None = None
) -> dict[str, Any]:
    """Fill ``v``, ``iat``, ``nonce`` and (with ``days``) ``exp`` when missing."""
    moment = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    filled = dict(payload)
    filled.setdefault("v", FORMAT_VERSION)
    filled.setdefault("iat", _rfc3339(moment))
    filled.setdefault("nonce", b64url_encode(secrets.token_bytes(16)))
    if "exp" not in filled:
        if days is None:
            raise ValueError("the payload has no exp; pass --days N")
        filled["exp"] = _rfc3339(moment + timedelta(days=days))
    return filled


def sign_payload(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Return licence file text for ``payload``; raises LicenseInvalid if it is malformed."""
    body = canonical_payload(payload)
    token = f"{b64url_encode(body)}.{b64url_encode(private_key.sign(body))}"
    parse_license(token, public_key=private_key.public_key())
    return token


def load_private_key(pem: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("the signing key is not an Ed25519 private key")
    return key


def private_key_from_env() -> Ed25519PrivateKey:
    path = os.environ.get(KEY_PATH_ENV)
    if not path:
        raise ValueError(f"set {KEY_PATH_ENV} to the private key path, or pass --keychain")
    return load_private_key(Path(path).expanduser().read_bytes())


def private_key_from_keychain() -> Ed25519PrivateKey:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(
            f"no Keychain item {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT} (security exited "
            f"{proc.returncode})"
        )
    secret = proc.stdout.strip()
    # `security -w` prints a secret with newlines (a PEM) as hex.
    if not secret.startswith("-----BEGIN"):
        try:
            secret = bytes.fromhex(secret).decode("utf-8")
        except ValueError:
            raise ValueError("the Keychain item is not a PEM private key") from None
    return load_private_key(secret.encode("utf-8"))


def signs_for_this_build(private_key: Ed25519PrivateKey) -> bool:
    raw = serialization.Encoding.Raw, serialization.PublicFormat.Raw
    return private_key.public_key().public_bytes(*raw) == embedded_public_key().public_bytes(*raw)


def _rfc3339(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sign an Observatory licence payload.")
    parser.add_argument("payload", help="payload JSON file, or - for stdin")
    parser.add_argument("--days", type=int, help="set exp this many days after iat if missing")
    parser.add_argument("--out", type=Path, help="write the licence here instead of stdout")
    parser.add_argument(
        "--keychain", action="store_true", help="read the key from the macOS login Keychain"
    )
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("the payload must be a JSON object")
        private_key = private_key_from_keychain() if args.keychain else private_key_from_env()
        token = sign_payload(complete_payload(payload, days=args.days), private_key)
    except (OSError, ValueError, LicenseInvalid) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not signs_for_this_build(private_key):
        print(
            "note: this key is not the one embedded in packages/py/licensing/keys.py; "
            "Observatory builds will reject this licence (fine for tests).",
            file=sys.stderr,
        )
    if args.out:
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(token + "\n")
        print(f"Licence written to {args.out}", file=sys.stderr)
    else:
        print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
