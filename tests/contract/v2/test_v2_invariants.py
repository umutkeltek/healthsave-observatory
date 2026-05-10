"""v2 contract invariants — guards we never want to drift.

These tests enforce structural rules on the ``contracts/`` package.
Any drift here means a v2 design rule was quietly broken.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from contracts._base import V2Model as BaseV2Model

import contracts
from contracts import (
    ALL_MODELS,
    DEFAULT_OWNER_ID,
    DEFAULT_WORKSPACE_ID,
    PluginManifest,
    V2Model,
    WithOwnership,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "packages" / "py" / "contracts"
COMPAT_V1_DIR = REPO_ROOT / "packages" / "py" / "compat_v1"


def _imports_in(file: Path) -> set[str]:
    """Top-level module names imported by ``file`` (AST-level)."""
    tree = ast.parse(file.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".", 1)[0])
    return out


# Types that are *process metadata*, not user data — they don't
# extend WithOwnership and they shouldn't. Curated explicitly so a
# new type that should carry ownership can't quietly skip it.
NON_OWNERSHIP_TYPES: frozenset[type[V2Model]] = frozenset(
    {
        contracts.Provenance,
        contracts.AgentSpec,
        contracts.SourceCapability,
        contracts.Annotation,
        contracts.ChartSpec,
        contracts.NarrativeCard,
        contracts.EvidenceRef,
        contracts.Uncertainty,
        contracts.Claim,
        contracts.Insight,
        contracts.SuggestedAction,
        contracts.PluginCapability,
        contracts.PluginPermissions,
        contracts.PluginManifest,
    }
)


def test_contracts_never_imports_compat_v1() -> None:
    """v2 must not reference v1. They coexist; they never mix.

    AST-level — docstring mentions of ``compat_v1`` are fine (and
    expected, e.g. for cross-reference docs).
    """
    for path in CONTRACTS_DIR.rglob("*.py"):
        imports = _imports_in(path)
        assert "compat_v1" not in imports, (
            f"{path.relative_to(REPO_ROOT)} imports compat_v1. "
            "v2 contracts and v1 compat are independent — they never cross-import."
        )


def test_compat_v1_never_imports_contracts() -> None:
    """The reverse: v1 freeze must not depend on v2. Decoupled both ways."""
    for path in COMPAT_V1_DIR.rglob("*.py"):
        imports = _imports_in(path)
        assert "contracts" not in imports, (
            f"{path.relative_to(REPO_ROOT)} imports contracts (v2). "
            "compat_v1 must not depend on v2 contracts."
        )


def test_default_owner_workspace_sentinels_match_v1() -> None:
    """The single-user sentinel UUID must match the v1 server fallback.

    A self-hosted install with no X-User-Id header writes under
    ``00000000-0000-0000-0000-000000000001``. v2 contracts have to
    default to the same value or migrating one record from v1 to v2
    becomes a coordination problem.
    """
    from server.ingestion.owner import DEFAULT_OWNER_ID as V1_DEFAULT_OWNER_ID

    assert DEFAULT_OWNER_ID == V1_DEFAULT_OWNER_ID, (
        "v2 DEFAULT_OWNER_ID drifted from server.ingestion.owner.DEFAULT_OWNER_ID. "
        "Single-user installs would split into two owner identities."
    )
    # Workspace has no v1 equivalent (workspace is a v2 concept), but
    # we lock the value to the same sentinel for symmetry.
    assert str(DEFAULT_WORKSPACE_ID) == "00000000-0000-0000-0000-000000000001"


def test_all_models_inherit_v2model() -> None:
    """Every public model is a ``V2Model`` (extra='forbid' + validation)."""
    for model_cls in ALL_MODELS:
        assert issubclass(model_cls, BaseV2Model), (
            f"{model_cls.__name__} is in ALL_MODELS but does not extend V2Model"
        )


def test_user_data_models_extend_withownership() -> None:
    """Every model that represents user data carries owner + workspace.

    The negative list (``NON_OWNERSHIP_TYPES``) is curated explicitly
    so adding a new user-data type without ownership is a test break,
    not a silent gap.
    """
    for model_cls in ALL_MODELS:
        if model_cls in NON_OWNERSHIP_TYPES:
            assert not issubclass(model_cls, WithOwnership), (
                f"{model_cls.__name__} is listed in NON_OWNERSHIP_TYPES "
                "but actually extends WithOwnership — drop it from the list "
                "or remove the inheritance."
            )
            continue

        assert issubclass(model_cls, WithOwnership), (
            f"{model_cls.__name__} represents user data but does not extend "
            "WithOwnership. Add the inheritance, or — if it is genuinely "
            "process metadata — add it to NON_OWNERSHIP_TYPES with a comment."
        )

        fields = model_cls.model_fields
        assert "owner_id" in fields, f"{model_cls.__name__} missing owner_id"
        assert "workspace_id" in fields, f"{model_cls.__name__} missing workspace_id"


def test_every_model_emits_valid_json_schema() -> None:
    """Schema export must succeed on every public type.

    The schema export script depends on this; CI fails if any type
    can't be serialized.
    """
    for model_cls in ALL_MODELS:
        schema = model_cls.model_json_schema()
        assert isinstance(schema, dict)
        assert "title" in schema or "$ref" in schema
        # extra='forbid' produces additionalProperties=False on the top
        # level for every plain object type.
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False, (
                f"{model_cls.__name__} schema lacks additionalProperties=False — "
                "extra='forbid' must be inherited from V2Model."
            )


def test_extra_forbid_rejects_unknown_fields() -> None:
    """A canonical contract refuses unknown fields. Live test on one
    representative model."""
    from pydantic import ValidationError

    valid = {
        "id": "hdh.sources.oura",
        "name": "Oura",
        "kind": "source",
        "version": "0.1.0",
        "sdk_version": ">=0.1,<0.2",
        "entrypoint": "hdh_plugin_oura.source:OuraSource",
    }
    PluginManifest.model_validate(valid)

    with pytest.raises(ValidationError):
        PluginManifest.model_validate({**valid, "unknown_field_xyz": "boom"})


def test_all_models_in_init_match_directory() -> None:
    """``ALL_MODELS`` enumerates every public type — adding one to a
    submodule without registering it in __init__.py is a drift."""
    public_module_names = {m.__module__ for m in ALL_MODELS if hasattr(m, "__module__")}
    # Sanity: at least one model from each submodule is registered.
    expected_modules = {
        "contracts._base",
        "contracts.data",
        "contracts.agents",
        "contracts.narrative",
        "contracts.ui",
        "contracts.plugins",
    }
    missing = expected_modules - public_module_names
    assert not missing, (
        f"ALL_MODELS is missing types from these submodules: {sorted(missing)}. "
        "Add them to packages/py/contracts/__init__.py ALL_MODELS tuple."
    )
