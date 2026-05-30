"""GET ``/api/v2/meta`` — the v2 version surface.

Phase 0 of the datahub v2 (device-agnostic canonical hub) build. The
dashboard, plugins, and the replay orchestrator all need to read the
distinct version axes that the architecture deliberately keeps separate
(Decision H in ``docs/plans/2026-05-30-architecture-decision-record.md``):

  * ``api_contract`` — the iOS-locked v1 wire contract; never moves.
  * ``ontology``     — the metric registry version (Phase 1+).
  * ``normalizer``   — source→canonical parsing logic version.
  * ``fusion_policy``— multi-source best-value selection semantics.

Tying ontology to API version is explicitly rejected: ``/api/v2`` can stay
stable while the ontology rolls forward. This route is additive and lives
under the established ``/api/v2/`` namespace alongside ``v2_agents`` and
``sync`` — it does not touch any v1 surface.
"""

from __future__ import annotations

from fastapi import APIRouter

# Version axes — single source of truth until the ontology package (Phase 1)
# owns ``ontology_version``. Kept here, not in v1, so the locked contract is
# never implicated by a version bump.
API_CONTRACT_VERSION = "v1"
V2_STATUS = "in-development"
ONTOLOGY_VERSION = "2026.05.0-draft"
NORMALIZER_VERSION = "0"  # no v2 canonical normalizer yet (Phase 1 introduces it)
FUSION_POLICY_VERSION = "0"  # no fusion layer yet (Phase 5 introduces it)

router = APIRouter(prefix="/api/v2")


@router.get("/meta")
async def v2_meta() -> dict:
    """Return the v2 version axes. Unauthenticated, read-only, no health data."""
    return {
        "v2_status": V2_STATUS,
        "versions": {
            "api_contract": API_CONTRACT_VERSION,
            "ontology": ONTOLOGY_VERSION,
            "normalizer": NORMALIZER_VERSION,
            "fusion_policy": FUSION_POLICY_VERSION,
        },
        "decision_record": "docs/plans/2026-05-30-architecture-decision-record.md",
    }
