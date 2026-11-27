"""Make an Ed25519 keypair for TEST Observatory licences.

Usage:
    python scripts/license_keygen.py PRIVATE_KEY_PATH

Writes the private key (PKCS8 PEM, mode 0600) to PRIVATE_KEY_PATH, which must be
outside this repository and must not exist yet, and prints the public key as
``packages/py/licensing/keys.py`` spells it (raw base64url) and as PEM.

The production signing key already exists and lives only with the billing
service. Do not paste a test public key into ``licensing/keys.py``: every real
licence would stop verifying (``tests/test_licensing.py`` pins the real key).
Sign test licences with ``scripts/license_sign.py``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def generate_keypair() -> tuple[bytes, str, str]:
    """Return (private PKCS8 PEM, public raw base64url, public SPKI PEM)."""
    import base64

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_b64url = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    return private_pem, public_b64url, public_pem


def write_private_key(path: Path, private_pem: bytes, *, repo_root: Path = ROOT) -> Path:
    """Write the key with mode 0600. Refuses a path inside the repo or an existing file."""
    target = path.expanduser().resolve()
    if target.is_relative_to(repo_root.resolve()):
        raise ValueError(f"refusing to write a private key inside the repository ({target})")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(private_pem)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make an Ed25519 keypair for TEST licences.")
    parser.add_argument("private_key_path", type=Path, help="where to write the private key")
    args = parser.parse_args(argv)
    private_pem, public_b64url, public_pem = generate_keypair()
    try:
        target = write_private_key(args.private_key_path, private_pem)
    except FileExistsError:
        print(f"error: {args.private_key_path} already exists; not overwriting.", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Private key written to {target} (mode 0600). Keep it out of every repository.")
    print("Public key, raw base64url (the form licensing/keys.py uses):")
    print(public_b64url)
    print("Public key, PEM:")
    print(public_pem, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
