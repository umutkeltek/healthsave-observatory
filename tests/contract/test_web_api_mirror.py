"""Web ``api.ts`` ↔ v2 route-projection drift gate.

The Observatory web app's ``apps/web/app/lib/api.ts`` types are
hand-written mirrors of the v2 route *projections* (the dicts the
handlers literally return) — NOT the contract models in
``packages/py/contracts`` and NOT the generated TS client. The
generated-client drift gate therefore does not protect them: a handler
could rename a key and the web app would render blanks with every gate
green.

This test closes that hole mechanically, both repos' halves living in
this repo: it parses the field names of every api.ts response type the
web app decodes (via ``getJson``/``postJson``), expands referenced
types transitively, and asserts each field is *emittable* by the route
module that serves it — as a dict-literal key, a SQL ``AS`` alias, or a
Pydantic model field defined/imported in that module.

Direction: this catches the server dropping/renaming a key the web
reads. It deliberately does NOT require the web to model every server
key (additive server fields are fine).
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
API_TS = REPO_ROOT / "apps" / "web" / "app" / "lib" / "api.ts"

# Root response type (api.ts) -> server modules whose source/models emit it.
# Mirrors the getJson/postJson calls in api.ts; extend both together.
TYPE_TO_MODULES: dict[str, list[str]] = {
    "MetricSummary": ["server.api.v2_metrics"],
    "MetricSeries": ["server.api.v2_metrics"],
    "SeriesBatch": ["server.api.v2_metrics"],
    "Receipts": ["server.api.v2_receipts"],
    "Readiness": ["server.api.v2_readiness"],
    "InsightsLatest": ["server.api.v2_insights"],
    "FindingsList": ["server.api.v2_insights"],
    "Candidates": ["server.api.v2_experiments"],
    "ExperimentList": ["server.api.v2_experiments"],
    "Experiment": ["server.api.v2_experiments"],
    "Privacy": ["server.api.v2_privacy"],
    "IntelligenceView": ["server.api.v2_intelligence"],
    "DetectLocalResult": ["server.api.v2_intelligence"],
    "TestConnectionResult": ["server.api.v2_intelligence"],
    "SourcesResponse": ["server.api.v2_identity"],
    "StreamsResponse": ["server.api.v2_identity"],
    "DevicesResponse": ["server.api.v2_identity"],
}


def _parse_api_ts() -> dict[str, dict[str, str]]:
    """api.ts object types -> {field name: field type expression}.

    Brace-matched (not line-based) so single-line types like
    ``export type SourcesResponse = { count: number; sources: ... };``
    and nested inline object types parse correctly.
    """
    source = API_TS.read_text()
    types: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"export type (\w+) = ([\w&\s|]*?)\{", source):
        name, intersected = match.group(1), match.group(2)
        depth, start = 1, match.end()
        pos = start
        while depth and pos < len(source):
            if source[pos] == "{":
                depth += 1
            elif source[pos] == "}":
                depth -= 1
            pos += 1
        body = source[start : pos - 1]
        fields: dict[str, str] = {}
        for field in re.finditer(r"(\w+)\??:\s*([^;{}]+|[^;]*?\{[^}]*\}[^;]*)(?:;|$)", body):
            fields[field.group(1)] = field.group(2)
        # `A & { ... }` intersection: pull the referenced type in too.
        for base in re.findall(r"(\w+)\s*&", intersected):
            fields[f"__extends_{base}"] = base
        types[name] = fields
    return types


def _expand_fields(root: str, types: dict[str, dict[str, str]]) -> set[str]:
    """All field names of ``root`` plus every api.ts type it references."""
    seen_types: set[str] = set()
    fields: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in seen_types or current not in types:
            continue
        seen_types.add(current)
        for field, type_expr in types[current].items():
            if field.startswith("__extends_"):
                stack.append(type_expr)
                continue
            fields.add(field)
            stack.extend(t for t in re.findall(r"\b([A-Z]\w+)\b", type_expr) if t in types)
    return fields


def _emittable_keys(module_name: str) -> set[str]:
    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    keys = set(re.findall(r'"([a-z][a-z0-9_]*)":', source))
    keys |= set(re.findall(r"\bAS\s+([a-z][a-z0-9_]*)", source))
    for obj in vars(module).values():
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
            keys |= set(obj.model_fields.keys())
    return keys


@pytest.mark.parametrize("root_type", sorted(TYPE_TO_MODULES))
def test_web_type_fields_are_emitted_by_server(root_type: str) -> None:
    types = _parse_api_ts()
    assert root_type in types, (
        f"api.ts no longer declares {root_type} — update TYPE_TO_MODULES "
        "together with apps/web/app/lib/api.ts"
    )
    expected = _expand_fields(root_type, types)
    emittable: set[str] = set()
    for module_name in TYPE_TO_MODULES[root_type]:
        emittable |= _emittable_keys(module_name)

    missing = expected - emittable
    assert not missing, (
        f"web type {root_type} expects fields the server modules "
        f"{TYPE_TO_MODULES[root_type]} no longer emit: {sorted(missing)}. "
        "Either the handler renamed/dropped a key (fix the server or update "
        "api.ts deliberately) or the key moved to another module (extend the "
        "module list for this type)."
    )


def test_every_getjson_root_type_is_gated() -> None:
    """Every response type api.ts decodes must have a module mapping."""
    source = API_TS.read_text()
    roots = set(re.findall(r"(?:getJson|postJson)<(\w+)", source))
    roots -= {"T"}
    # Array element types: getJson<MetricSummary[]> -> MetricSummary
    roots |= {m for m in re.findall(r"(?:getJson|postJson)<(\w+)\[\]>", source)}
    unmapped = roots - set(TYPE_TO_MODULES)
    assert not unmapped, (
        f"api.ts decodes response types with no drift gate: {sorted(unmapped)}. "
        "Add them to TYPE_TO_MODULES."
    )
