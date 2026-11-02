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

from scripts.release_notes import (
    absolute_links,
    changelog_section,
    problems,
    pyproject_version,
)


def test_main_is_releasable_at_its_stated_version() -> None:
    version = pyproject_version()
    assert problems(version) == []


def _fake_repo(
    tmp_path: Path,
    *,
    pyproject: str,
    app: str,
    lock: str,
    changelog: str,
    compose: str | None = None,
) -> Path:
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
    tag = compose if compose is not None else pyproject
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  api:\n"
        f"    image: ghcr.io/o/observatory:${{HEALTHSAVE_VERSION:-v{tag}}}\n"
        "  web:\n"
        f"    image: ghcr.io/o/observatory-web:${{HEALTHSAVE_VERSION:-v{tag}}}\n"
    )
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


def test_release_page_links_point_at_the_tagged_files() -> None:
    base = "https://github.com/o/r/blob/v1.1.0/"
    notes = (
        "See [UPGRADING.md](UPGRADING.md), [docs](docs/a.md#b), "
        "[#45](https://github.com/o/r/issues/45), [here](#upgrade), [mail](mailto:x@y.z)."
    )
    assert absolute_links(notes, base) == (
        f"See [UPGRADING.md]({base}UPGRADING.md), [docs]({base}docs/a.md#b), "
        "[#45](https://github.com/o/r/issues/45), [here](#upgrade), [mail](mailto:x@y.z)."
    )


def test_compose_must_pull_the_release_images(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        pyproject="1.2.0",
        app="1.2.0",
        lock="1.2.0",
        changelog="## [1.2.0] - 2026-11-02\n\n- notes\n",
        compose="1.1.0",
    )
    assert problems("1.2.0", root) == [
        "docker-compose.yml pulls 1.1.0, release is 1.2.0",
    ]


def test_compose_without_release_images_is_named(tmp_path: Path) -> None:
    root = _fake_repo(
        tmp_path,
        pyproject="1.2.0",
        app="1.2.0",
        lock="1.2.0",
        changelog="## [1.2.0] - 2026-11-02\n\n- notes\n",
    )
    (root / "docker-compose.yml").write_text("services:\n  api:\n    build: .\n")
    assert problems("1.2.0", root) == [
        "docker-compose.yml pulls no ghcr.io release image, release is 1.2.0",
    ]
