"""Regenerate ``contracts/json-schema/*.json`` — one per public v2 type.

Same shape as ``generate_v1_lock``: source of truth is the Pydantic
models in ``packages/py/contracts``; the JSON Schema files committed
to the repo are *generated*. CI fails the build if regen produces
an uncommitted diff.

> **Reproducibility.** JSON Schema output is sensitive to Pydantic's
> minor version. **Always regenerate inside Docker** (which pins the
> same versions production and CI use):
>
>     make regen-v2-schemas
>
> Running this script directly on a host with a different Pydantic
> version produces serializer-noise drift that fails CI even when
> the contracts are unchanged. The Makefile target builds the
> project's Docker image and regenerates from there.

Usage:
    python -m scripts.generate_v2_schemas          # writes schema files
    python -m scripts.generate_v2_schemas --check  # exits 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Allow the output dir to be overridden via env var. The Docker-pinned
# Makefile target mounts the host's contracts/json-schema/ at a
# different in-container path (the /app/contracts/ dir is occupied by
# the Python package of the same name) and sets SCHEMAS_OUTPUT_DIR
# to that mount point.
import os  # noqa: E402

SCHEMAS_DIR = Path(
    os.environ.get("SCHEMAS_OUTPUT_DIR", str(REPO_ROOT / "contracts" / "json-schema"))
)

_PINNED_PYDANTIC = "2.9.2"


def _runtime_versions_match_pinned() -> tuple[bool, str]:
    try:
        import pydantic
    except ImportError as exc:
        return False, str(exc)
    pydantic_v = getattr(pydantic, "VERSION", "unknown")
    if pydantic_v != _PINNED_PYDANTIC:
        return False, f"runtime pydantic={pydantic_v}; pinned pydantic=={_PINNED_PYDANTIC}"
    return True, ""


def _serialize(model_cls) -> str:
    schema = model_cls.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any committed schema differs from the live one.",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    sys.path.insert(0, str(REPO_ROOT / "packages" / "py"))
    from contracts import ALL_MODELS

    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)

    if args.check:
        matched, reason = _runtime_versions_match_pinned()
        if not matched:
            print(
                f"SKIP: runtime Pydantic does not match the pinned env: {reason}. "
                "Use `make regen-v2-schemas` (Docker) for any drift work.",
                file=sys.stderr,
            )
            return 0

        drifted: list[str] = []
        for model_cls in ALL_MODELS:
            target = SCHEMAS_DIR / f"{model_cls.__name__}.json"
            if not target.exists():
                drifted.append(f"missing: {target.relative_to(REPO_ROOT)}")
                continue
            committed = target.read_text()
            live = _serialize(model_cls)
            if committed != live:
                drifted.append(f"diff: {target.relative_to(REPO_ROOT)}")

        # Bundle drift check
        from pydantic.json_schema import models_json_schema  # noqa: PLC0415

        bundle_path = SCHEMAS_DIR / "_bundle.json"
        _defs_pairs, bundle = models_json_schema(
            [(m, "validation") for m in ALL_MODELS],
            ref_template="#/$defs/{model}",
        )
        bundle_live = json.dumps(bundle, indent=2, sort_keys=True) + "\n"
        if not bundle_path.exists():
            drifted.append(f"missing: {bundle_path.relative_to(REPO_ROOT)}")
        elif bundle_path.read_text() != bundle_live:
            drifted.append(f"diff: {bundle_path.relative_to(REPO_ROOT)}")

        if drifted:
            print(
                "v2 JSON Schema drift detected:\n  " + "\n  ".join(drifted),
                file=sys.stderr,
            )
            print(
                "If intentional, run `make regen-v2-schemas` and commit the diff.",
                file=sys.stderr,
            )
            return 1
        print(f"v2 JSON Schemas match: {len(ALL_MODELS)} files in {SCHEMAS_DIR}")
        return 0

    written = 0
    for model_cls in ALL_MODELS:
        target = SCHEMAS_DIR / f"{model_cls.__name__}.json"
        target.write_text(_serialize(model_cls))
        written += 1

    # Bundle: one JSON file with every type under $defs, deduped, with
    # cross-references intact. The TS codegen consumes this bundle so
    # it produces one TS file with no duplicated interface declarations.
    from pydantic.json_schema import models_json_schema  # noqa: PLC0415

    _defs_pairs, bundle = models_json_schema(
        [(m, "validation") for m in ALL_MODELS],
        ref_template="#/$defs/{model}",
    )
    bundle_path = SCHEMAS_DIR / "_bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    print(f"wrote {written} schema files + 1 bundle to {SCHEMAS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
