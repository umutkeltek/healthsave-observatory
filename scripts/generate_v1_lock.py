"""Regenerate ``contracts/openapi/v1.locked.json``.

The lock file is the golden snapshot of the v1 OpenAPI surface. The
contract test (``tests/contract/api_v1/test_v1_contract.py``) compares
the live app's OpenAPI to this file and fails on any drift. Bump the
lock by running this script; commit the diff with a message that names
the v1 change and the iOS-app coordination plan.

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
        committed = LOCK_PATH.read_text()
        if committed != serialized:
            print(
                "v1 OpenAPI drift detected. "
                "If intentional, re-run without --check and commit the diff "
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
