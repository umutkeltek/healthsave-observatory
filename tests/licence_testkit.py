"""Helpers for tests that need Observatory licences signed by a throwaway key.

Real licences are signed by a key that never leaves the billing service, so
tests mint their own with a test keypair and point the verifier at it: in
process by patching ``licensing.keys.PUBLIC_KEY_B64URL``, and for the bash CLI
through ``HEALTHSAVE_PYTHON`` set to :func:`python_shim`, which applies the same
patch before running ``python -m licensing``.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "packages" / "py"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from licensing.verify import b64url_encode  # noqa: E402

from scripts.license_sign import sign_payload  # noqa: E402

ALL_CARE_FEATURES = ["care.backup.offsite", "care.restore.drill", "care.update.rollback"]


@dataclass(frozen=True)
class TestKey:
    __test__ = False  # not a pytest test class

    private_key: Ed25519PrivateKey

    @property
    def public_b64url(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return b64url_encode(raw)


def make_key() -> TestKey:
    return TestKey(Ed25519PrivateKey.generate())


def payload(now: datetime | None = None, **overrides: Any) -> dict[str, Any]:
    moment = now or datetime.now(UTC)
    data: dict[str, Any] = {
        "v": 1,
        "tier": "care",
        "sub": "ctm_test_customer",
        "email_sha256": hashlib.sha256(b"test@example.com").hexdigest(),
        "seats": 1,
        "features": list(ALL_CARE_FEATURES),
        "iat": _rfc3339(moment - timedelta(days=1)),
        "exp": _rfc3339(moment + timedelta(days=365)),
        "nonce": b64url_encode(b"0123456789abcdef"),
    }
    data.update(overrides)
    return data


def mint(key: TestKey, **overrides: Any) -> str:
    """Licence file text signed by ``key``."""
    return sign_payload(payload(**overrides), key.private_key)


def expired(days_ago: int, **overrides: Any) -> dict[str, Any]:
    """Payload overrides for a licence that expired ``days_ago`` days ago."""
    now = datetime.now(UTC)
    return {
        "iat": _rfc3339(now - timedelta(days=days_ago + 365)),
        "exp": _rfc3339(now - timedelta(days=days_ago)),
        **overrides,
    }


def python_shim(directory: Path, key: TestKey) -> Path:
    """An executable to use as HEALTHSAVE_PYTHON that trusts ``key``.

    The CLI runs ``$HEALTHSAVE_PYTHON -m licensing ARGS``; the shim drops
    ``-m licensing`` and runs the same entry point with the test key embedded.
    """
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT / 'packages' / 'py')!r}); "
        "import licensing.keys as k; "
        f"k.PUBLIC_KEY_B64URL = {key.public_b64url!r}; "
        "from licensing.__main__ import main; "
        "sys.exit(main(sys.argv[1:]))"
    )
    shim = directory / "licensing-python"
    shim.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "-m" ] && [ "$2" = "licensing" ] || exit 97\n'
        "shift 2\n"
        f'exec {sys.executable!r} -c "{code}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
