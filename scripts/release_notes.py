"""Release gate for HealthSave Observatory tags.

One version, stated in three places that must agree before a tag ships:
``pyproject.toml``, the FastAPI app in ``apps/api/server/main.py`` (which
``contracts/openapi/v1.locked.json`` snapshots), and a ``## [X.Y.Z]`` section
in ``CHANGELOG.md`` that becomes the GitHub Release notes.

Usage:
    python scripts/release_notes.py 1.1.0          # check, then print the notes
    python scripts/release_notes.py 1.1.0 --check  # check only

Used by ``scripts/release.sh`` before tagging, by ``.github/workflows/release.yml``
before anything is published, and by ``tests/contract/test_release_version_coherence.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
APP_VERSION = re.compile(r'FastAPI\([^)]*\bversion="([^"]+)"')


def pyproject_version(root: Path = REPO_ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]


def app_version(root: Path = REPO_ROOT) -> str:
    source = (root / "apps/api/server/main.py").read_text()
    match = APP_VERSION.search(source)
    if match is None:
        raise ValueError('apps/api/server/main.py: no FastAPI(..., version="...") literal')
    return match.group(1)


def lock_version(root: Path = REPO_ROOT) -> str:
    lock = json.loads((root / "contracts/openapi/v1.locked.json").read_text())
    return lock["info"]["version"]


def changelog_section(version: str, root: Path = REPO_ROOT) -> str | None:
    """Body of ``## [version]`` up to the next ``## [`` heading, or None."""
    text = (root / "CHANGELOG.md").read_text()
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(text)
    if match is None:
        return None
    rest = text[match.end() :]
    following = re.search(r"^## \[", rest, re.MULTILINE)
    body = rest[: following.start()] if following else rest
    return body.strip() or None


def problems(version: str, root: Path = REPO_ROOT) -> list[str]:
    found: list[str] = []
    if not SEMVER.match(version):
        found.append(f"{version!r} is not X.Y.Z (tags are v<semver>, e.g. v1.1.0)")
    stated = {
        "pyproject.toml": pyproject_version(root),
        "apps/api/server/main.py": app_version(root),
        "contracts/openapi/v1.locked.json": lock_version(root),
    }
    for where, value in stated.items():
        if value != version:
            found.append(f"{where} says {value}, release is {version}")
    if changelog_section(version, root) is None:
        found.append(f"CHANGELOG.md has no non-empty '## [{version}]' section")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="X.Y.Z, without the leading v")
    parser.add_argument(
        "--check", action="store_true", help="validate only, print nothing on success"
    )
    args = parser.parse_args(argv)

    version = args.version.removeprefix("v")
    found = problems(version)
    if found:
        for problem in found:
            print(f"release check failed: {problem}", file=sys.stderr)
        return 1
    if not args.check:
        print(changelog_section(version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
