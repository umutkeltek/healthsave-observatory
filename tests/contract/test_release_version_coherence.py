"""The version a tag ships is stated once and agrees everywhere.

``pyproject.toml``, the FastAPI app, the OpenAPI lock and ``CHANGELOG.md``
must all name the same release; ``.github/workflows/release.yml`` refuses to
publish a tag otherwise. This test keeps main releasable between tags, so the
disagreement is caught on the commit that introduces it, not at tag time.
See RELEASING.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.release_notes import changelog_section, problems, pyproject_version


def test_main_is_releasable_at_its_stated_version() -> None:
    version = pyproject_version()
    assert problems(version) == []


def _fake_repo(tmp_path: Path, *, pyproject: str, app: str, lock: str, changelog: str) -> Path:
    (tmp_path / "apps/api/server").mkdir(parents=True)
    (tmp_path / "contracts/openapi").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{pyproject}"\n')
    (tmp_path / "apps/api/server/main.py").write_text(
        f'app = FastAPI(title="HealthSave Observatory", version="{app}", lifespan=lifespan)\n'
    )
    (tmp_path / "contracts/openapi/v1.locked.json").write_text(
        json.dumps({"info": {"version": lock}})
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return tmp_path


def test_every_disagreeing_source_is_named(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        pyproject="1.2.0",
        app="1.1.0",
        lock="1.0.0",
        changelog="# Changelog\n\n## [1.1.0] - 2026-10-04\n\n- notes\n",
    )
    found = problems("1.2.0", root)
    assert any("apps/api/server/main.py says 1.1.0" in p for p in found)
    assert any("v1.locked.json says 1.0.0" in p for p in found)
    assert any("no non-empty '## [1.2.0]' section" in p for p in found)
    assert not any(p.startswith("pyproject.toml") for p in found)


def test_tags_must_be_plain_semver(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        pyproject="1.1",
        app="1.1",
        lock="1.1",
        changelog="## [1.1]\n\n- notes\n",
    )
    assert any("not X.Y.Z" in p for p in problems("1.1", root))


def test_release_notes_are_exactly_one_section(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        pyproject="1.1.0",
        app="1.1.0",
        lock="1.1.0",
        changelog=(
            "# Changelog\n\n"
            "## [1.1.1] - 2026-10-10\n\n- newer\n\n"
            "## [1.1.0] - 2026-10-04\n\n### Fixed\n\n- this one\n\n"
            "## [1.0.0] - 2026-05-03\n\n- older\n"
        ),
    )
    assert changelog_section("1.1.0", root) == "### Fixed\n\n- this one"
    assert changelog_section("1.0.1", root) is None
