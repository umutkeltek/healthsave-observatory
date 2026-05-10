"""Regenerate ``contracts/openapi/v1.locked.json``.

The lock file is the golden snapshot of the v1 OpenAPI surface. The
contract test (``tests/contract/api_v1/test_v1_contract.py``) compares
the live app's OpenAPI to this file and fails on any drift. Bump the
lock by running this script; commit the diff with a message that names
the v1 change and the iOS-app coordination plan.

> **IMPORTANT — reproducibility.** The OpenAPI JSON depends on the
> installed FastAPI + Pydantic versions; running this on a host with
> different versions than the project's pinned ones produces
> serializer-noise drift that fails CI even when the wire contract is
> unchanged. **Always regenerate the lock inside the Docker image**
> (which pins the same versions production and CI use):
>
>     make regen-lock
>
> Equivalent to:
>     docker build -t hdh-lockgen . \\
>     && docker run --rm hdh-lockgen \\
>         python -m scripts.generate_v1_lock > contracts/openapi/v1.locked.json
>
> Running this script directly on a different host Python is fine for
> ``--check`` debugging but never the source of truth for the lock file.

Usage:
    python -m scripts.generate_v1_lock          # writes the lock file
    python -m scripts.generate_v1_lock --check  # exits 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "contracts" / "openapi" / "v1.locked.json"


def dump_openapi() -> dict:
    # v2 layout: server lives under apps/api/, analysis under packages/py/.
    # Add both roots to sys.path so this script works on a fresh checkout
    # without requiring `pip install -e .` first. CI installs the package
    # before running the --check step; this is the safety net for local.
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    sys.path.insert(0, str(REPO_ROOT / "packages" / "py"))
    from server.main import app  # noqa: E402

    return app.openapi()


_PINNED_FASTAPI = "0.115.0"
_PINNED_PYDANTIC = "2.9.2"


def _runtime_versions_match_pinned() -> tuple[bool, str]:
    try:
        import fastapi
        import pydantic
    except ImportError as exc:
        return False, str(exc)
    fastapi_v = getattr(fastapi, "__version__", "unknown")
    pydantic_v = getattr(pydantic, "VERSION", "unknown")
    if fastapi_v != _PINNED_FASTAPI or pydantic_v != _PINNED_PYDANTIC:
        return False, (
            f"runtime fastapi={fastapi_v}, pydantic={pydantic_v}; "
            f"pinned fastapi=={_PINNED_FASTAPI}, pydantic=={_PINNED_PYDANTIC}"
        )
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the live OpenAPI differs from the lock file.",
    )
    args = parser.parse_args()

    live = dump_openapi()
    serialized = json.dumps(live, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not LOCK_PATH.exists():
            print(f"missing lock file: {LOCK_PATH}", file=sys.stderr)
            return 1

        matched, reason = _runtime_versions_match_pinned()
        if not matched:
            print(
                f"SKIP: runtime FastAPI/Pydantic do not match the pinned env: {reason}. "
                "The lock is byte-exact only under the pinned versions. "
                "Use `make regen-lock` (Docker) for any drift work.",
                file=sys.stderr,
            )
            return 0

        committed = LOCK_PATH.read_text()
        if committed != serialized:
            print(
                "v1 OpenAPI drift detected. "
                "If intentional, run `make regen-lock` and commit the diff "
                "alongside an iOS-coordination note.",
                file=sys.stderr,
            )
            return 1
        print(f"v1 OpenAPI lock matches: {LOCK_PATH}")
        return 0

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(serialized)
    print(f"wrote {LOCK_PATH} ({len(serialized)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
