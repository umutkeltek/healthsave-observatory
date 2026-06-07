"""RELIABILITY-004: canonical-normalizer rejections are counted per reason.

hdh_canonical_dual_write{result=rejected} is a faceless scalar; this adds
hdh_canonical_rejected{metric, reason} so a systematic mapping regression is
visible. Reason labels are bounded by stripping dynamic suffixes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from server.api.ingest import _rejection_reason_label  # noqa: E402

from tests.test_api_contract import FakeRequest, FakeSession  # noqa: E402


def test_reason_label_strips_dynamic_suffix():
    assert _rejection_reason_label("unmapped_metric:heart_rate") == "unmapped_metric"
    assert _rejection_reason_label("unmappable_code:Core") == "unmappable_code"
    assert _rejection_reason_label("missing_value") == "missing_value"


@pytest.mark.asyncio
async def test_unmapped_metric_increments_canonical_rejected_with_reason():
    from observability.metrics import CANONICAL_REJECTED, reset_metrics

    reset_metrics()
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "made_up_metric",
            "samples": [{"date": "2026-04-10T12:00:00Z", "qty": 1, "source": "x"}],
        }
    )

    await server.apple_batch(request, session)

    value = CANONICAL_REJECTED.labels(
        metric="made_up_metric", reason="unmapped_metric"
    )._value.get()
    assert value == 1.0
