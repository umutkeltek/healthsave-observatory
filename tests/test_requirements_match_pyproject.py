"""Packaging guard (#26 follow-up): the Docker image installs ``requirements.txt``
(``RUN pip install -r requirements.txt`` in the Dockerfile), NOT the project's
``pyproject.toml``. A dependency declared only in ``[project] dependencies``
therefore passes every local test (the dev venv is installed from pyproject) and
is missing in the container. That is exactly how scipy went absent for months:
``analysis/statistical`` imports ``scipy.stats`` lazily inside the correlation,
trend and experiment paths, so the API booted fine and correlation analysis then
died with ``ModuleNotFoundError: No module named 'scipy'``.

The rule: the two files carry the same runtime dependency lines. Dev-only
tooling belongs in ``[project.optional-dependencies]``, never in requirements.txt.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _normalize(spec: str) -> str:
    # Collapse whitespace and casing so "SciPy >= 1.14.0" == "scipy>=1.14.0".
    return re.sub(r"\s+", "", spec.strip()).lower().replace("_", "-")


def _name(spec: str) -> str:
    return re.split(r"[\[<>=!~;]", _normalize(spec), maxsplit=1)[0]


def _pyproject_runtime_deps() -> list[str]:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    return [_normalize(d) for d in data["project"]["dependencies"]]


def _requirements_lines() -> list[str]:
    lines = (_ROOT / "requirements.txt").read_text().splitlines()
    return [
        _normalize(line) for line in lines if line.strip() and not line.lstrip().startswith("#")
    ]


def test_dockerfile_installs_from_requirements_txt():
    # Sanity: the guard only matters while the image is built from requirements.txt.
    # If the Dockerfile ever switches to `pip install .`, retire this file deliberately.
    dockerfile = (_ROOT / "Dockerfile").read_text()
    assert "requirements.txt" in dockerfile


def test_every_pyproject_runtime_dependency_is_in_requirements_txt():
    required = {_name(d) for d in _pyproject_runtime_deps()}
    shipped = {_name(line) for line in _requirements_lines()}
    missing = sorted(required - shipped)
    assert missing == [], (
        f"requirements.txt is missing runtime dependencies declared in pyproject.toml: {missing}. "
        "The Docker image installs requirements.txt, so these are absent in the container."
    )


def test_requirements_txt_declares_nothing_pyproject_does_not():
    required = {_name(d) for d in _pyproject_runtime_deps()}
    shipped = {_name(line) for line in _requirements_lines()}
    extra = sorted(shipped - required)
    assert extra == [], (
        f"requirements.txt lists dependencies pyproject.toml does not declare: {extra}. "
        "Declare them in [project] dependencies (runtime) or [project.optional-dependencies] (dev)."
    )


def test_runtime_dependency_specs_are_identical_in_both_files():
    # Same line in both files, so a version bump cannot land in one and not the other.
    assert sorted(_pyproject_runtime_deps()) == sorted(_requirements_lines())


def test_scipy_is_a_runtime_dependency_in_both_files():
    # Pins the #26 regression by name: analysis/statistical imports scipy.stats.
    assert "scipy" in {_name(d) for d in _pyproject_runtime_deps()}
    assert "scipy" in {_name(line) for line in _requirements_lines()}
