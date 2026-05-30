"""``/api/v2/meta`` version surface — Phase 0 v2 contract.

The route must exist, stay additive (no v1 impact), and expose the four
distinct version axes the architecture keeps separate (Decision H:
api_contract / ontology / normalizer / fusion_policy).
"""

from __future__ import annotations

import pytest
from server.api.v2_meta import v2_meta


def test_meta_route_is_mounted() -> None:
    from server.main import app

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v2/meta" in paths


@pytest.mark.asyncio
async def test_meta_exposes_separate_version_axes() -> None:
    body = await v2_meta()
    versions = body["versions"]
    assert set(versions) == {"api_contract", "ontology", "normalizer", "fusion_policy"}
    # The iOS-locked contract axis must read v1 and must never be coupled to
    # the ontology axis (Decision H explicitly rejects that coupling).
    assert versions["api_contract"] == "v1"
