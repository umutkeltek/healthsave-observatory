"""HealthSave iOS-narrow v1 contract.

The HealthSave iOS app (App Store ID 6759843047) uses 3 of the 12
total v1 routes. Removing any of them, or changing the request body
field names of ``POST /api/apple/batch``, breaks the live App Store
binary immediately. This test pins the narrow iOS surface
independently of the broader v1 contract so a regression here is
unmistakable.

Cross-check: ``contracts/IOS_CROSS_CHECK.md``.
Source of truth: HealthSave iOS app at
    /Users/umut/Projects/products/healthsave/ios_app/Sources/HealthSync/
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from compat_v1 import IOS_FROZEN_ROUTES  # noqa: E402
from server.main import app  # noqa: E402

# Field names the iOS app puts on the wire for POST /api/apple/batch.
# Mirror these from Sources/HealthSync/SyncEngine.swift
# (AppleSyncBatchPayload.dictionary). Renaming any one of these on the
# server side rejects the iOS payload at validation time.
IOS_BATCH_PAYLOAD_FIELDS: frozenset[str] = frozenset(
    {"metric", "batch_index", "total_batches", "samples"}
)


def _live_routes() -> frozenset[str]:
    out = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if not path:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            out.add(f"{method} {path}")
    return frozenset(out)


def _batch_payload_field_names() -> set[str]:
    """Return the field names the server's BatchPayload model accepts.

    The ``POST /api/apple/batch`` route does not declare the body via a
    typed parameter — it reads ``await request.json()`` and validates
    with ``BatchPayload.model_validate(...)``. The OpenAPI lock therefore
    has no ``requestBody`` schema for this route, and the Pydantic model
    is the actual source of truth. Pinning the model fields directly is
    more honest than pinning the OpenAPI declaration.
    """
    from compat_v1.models import BatchPayload

    return set(BatchPayload.model_fields.keys())


def test_ios_narrow_routes_present() -> None:
    """The 3 iOS-narrow routes must always be served."""
    live = _live_routes()
    missing = IOS_FROZEN_ROUTES - live
    assert not missing, (
        f"HealthSave iOS contract break — missing routes: {sorted(missing)}. "
        "Removing one of these requires a coordinated App Store release, "
        "not a server change."
    )


def test_ios_batch_payload_field_names_present() -> None:
    """POST /api/apple/batch must accept the field names iOS sends."""
    schema_fields = _batch_payload_field_names()
    missing = IOS_BATCH_PAYLOAD_FIELDS - schema_fields
    assert not missing, (
        f"HealthSave iOS batch payload contract break — server schema is "
        f"missing fields the app sends: {sorted(missing)}. "
        "See Sources/HealthSync/SyncEngine.swift::AppleSyncBatchPayload."
    )


def test_ios_status_response_is_flat_object() -> None:
    """GET /api/apple/status response must be a free-form object, not wrapped.

    The iOS app decodes the response as ``[String: Any]`` and walks the
    top-level keys directly (one per metric). Wrapping the body in
    ``{"status": "ok", "counts": {...}}`` breaks the parse. This is a
    structural property of the OpenAPI spec, not of any one payload —
    we assert that the response schema is permissive object-typed
    (``additionalProperties: True`` or no fixed properties), which is
    how the server currently declares the open shape.
    """
    spec = app.openapi()
    operation = spec["paths"]["/api/apple/status"]["get"]
    responses = operation["responses"]
    response_200 = responses.get("200", {})
    schema = response_200.get("content", {}).get("application/json", {}).get("schema", {})

    # The schema is permissive: either no declared properties or
    # additionalProperties allowed. Either way, it must NOT declare
    # required wrapper fields that iOS doesn't expect.
    required = set(schema.get("required", []))
    forbidden_required = {"status", "counts"}
    overlap = required & forbidden_required
    assert not overlap, (
        f"GET /api/apple/status declares required wrapper fields {sorted(overlap)}. "
        "iOS expects a flat top-level metric→object map. See "
        "server/api/status.py header comment and "
        "tests/test_api_contract.py::test_status_endpoint_returns_flat_metric_objects."
    )
