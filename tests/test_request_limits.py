"""Request-bound guards (SECURITY-004): body-size middleware and export-limit
clamp. These are runtime guards, so the v1/v2 OpenAPI lock is unaffected. The
batch-size cap lives with the ingest harness in test_api_contract.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.api.v2_export as export_module  # noqa: E402
import server.main as main_module  # noqa: E402

# --- body-size middleware --------------------------------------------------


class _Req:
    def __init__(self, headers):
        self.headers = headers


async def _ok_next(request):
    return "passed-through"


@pytest.mark.asyncio
async def test_body_size_middleware_rejects_oversized_content_length(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    resp = await main_module.limit_request_body_size(_Req({"content-length": "101"}), _ok_next)
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_body_size_middleware_rejects_invalid_content_length(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    resp = await main_module.limit_request_body_size(
        _Req({"content-length": "not-a-number"}), _ok_next
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_body_size_middleware_passes_within_limit(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    result = await main_module.limit_request_body_size(_Req({"content-length": "50"}), _ok_next)
    assert result == "passed-through"


@pytest.mark.asyncio
async def test_body_size_middleware_passes_when_no_content_length(monkeypatch):
    monkeypatch.setattr(main_module, "MAX_REQUEST_BODY_BYTES", 100)
    result = await main_module.limit_request_body_size(_Req({}), _ok_next)
    assert result == "passed-through"


# --- export limit clamp ----------------------------------------------------


class _RecordingExportRepo:
    def __init__(self):
        self.limit = "unset"

    async def export_metric_json(self, session, *, metric, owner_id, date_from, date_to, limit):
        self.limit = limit
        return {"metric": metric, "rows": []}


@pytest.mark.asyncio
async def test_export_clamps_none_limit_to_ceiling(monkeypatch):
    repo = _RecordingExportRepo()
    monkeypatch.setattr(export_module, "_EXPORT_REPO", repo)
    await export_module.export_data(
        metric="heart_rate", format="json", limit=None, session=object()
    )
    assert repo.limit == export_module._MAX_EXPORT_LIMIT


@pytest.mark.asyncio
async def test_export_clamps_oversized_limit_to_ceiling(monkeypatch):
    repo = _RecordingExportRepo()
    monkeypatch.setattr(export_module, "_EXPORT_REPO", repo)
    await export_module.export_data(
        metric="heart_rate", format="json", limit=10_000_000, session=object()
    )
    assert repo.limit == export_module._MAX_EXPORT_LIMIT


@pytest.mark.asyncio
async def test_export_preserves_small_explicit_limit(monkeypatch):
    repo = _RecordingExportRepo()
    monkeypatch.setattr(export_module, "_EXPORT_REPO", repo)
    await export_module.export_data(metric="heart_rate", format="json", limit=25, session=object())
    assert repo.limit == 25
