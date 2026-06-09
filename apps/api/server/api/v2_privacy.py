"""GET ``/api/v2/privacy`` — the egress posture ("what leaves this host").

Surfaces the otherwise-invisible ADR-0001 Decision G trust boundary so the
dashboard can show, plainly, what does and doesn't leave the user's host. The
:class:`~analysis.egress.EgressPolicy` already enforces this fail-closed before
any byte is sent; this read exposes the *same* decision for display — it does
not decide anything itself.

Pure read: derives everything from the in-process analysis config + the pure
egress policy. No DB (no storage-zone import), no health data — just the
local-vs-cloud posture and the per-payload-class allow/deny breakdown.
"""

from __future__ import annotations

from typing import Any

from analysis.egress import (
    Destination,
    EgressPolicy,
    EgressRoute,
    PayloadClass,
    classify_destination,
)
from fastapi import APIRouter, Depends, Request

from .deps import verify_api_key

router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_api_key)])


@router.get("/privacy")
async def privacy(request: Request) -> dict:
    """The host's egress posture: provider, local-vs-cloud, and what may leave.

    ``raw_observations_leave_host`` is always ``false`` — the privacy promise is
    an invariant, enforced unconditionally by the policy regardless of opt-in.
    """
    llm = request.app.state.analysis_config.llm
    provider = llm.provider
    policy = EgressPolicy.from_config(llm)
    route = EgressRoute(provider=provider, base_url=getattr(llm, "base_url", None))
    destination = classify_destination(route, trusted_local_hosts=policy.trusted_local_hosts)
    is_local = destination is Destination.LOCAL

    # Per-payload-class breakdown straight from the policy, so the UI shows the
    # same verdicts the enforcement path uses (never a hand-maintained copy).
    egress: list[dict[str, Any]] = []
    raw_leaves = False
    for payload_class in PayloadClass:
        envelope = policy.evaluate(route=route, payload_class=payload_class)
        # "Leaves the host" only counts a CLOUD destination; a local model is
        # on-host, so an allowed local payload never leaves.
        leaves_host = envelope.allowed and not is_local
        if payload_class is PayloadClass.RAW_OBSERVATIONS and leaves_host:
            raw_leaves = True  # invariant guard — must stay false
        egress.append(
            {
                "payload_class": payload_class.value,
                "allowed": envelope.allowed,
                "leaves_host": leaves_host,
                "reason": envelope.reason,
            }
        )

    return {
        "provider": provider,
        "destination": destination.value,
        "is_local": is_local,
        "allow_cloud_egress": policy.allow_cloud,
        # True only when data actually crosses the boundary: a cloud provider
        # AND the explicit opt-in. A cloud provider without opt-in sends nothing.
        "cloud_active": not is_local and policy.allow_cloud,
        # Whether prompts are scrubbed of identifiers before a cloud send. Only
        # takes effect on the cloud path; the local model is never redacted.
        "cloud_prompt_redaction": bool(getattr(llm, "redact_cloud_prompts", True)),
        "raw_observations_leave_host": raw_leaves,
        "egress": egress,
    }
