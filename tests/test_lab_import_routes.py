"""HTTP review boundary with real parsing and fake transactional ports."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import server
from fastapi.testclient import TestClient
from server.api import deps
from server.api import v2_lab_imports as routes
from server.api.access import Principal, is_allowed
from server.api.deps import get_session

from tests.test_lab_document_review import CSV


@pytest.fixture
def setup(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    data = {}

    class Documents:
        async def linked_result_count(self, _session, identifier):
            return 1 if data[identifier]["committed_at"] else 0

        async def delete(self, _session, identifier, *, delete_results):
            row = data.pop(identifier)
            return int(bool(row["committed_at"]) and delete_results)

        async def create(self, _session, **kwargs):
            row = {
                **kwargs,
                "id": kwargs["document_id"],
                "created_at": datetime.now(UTC),
                "committed_at": None,
                "review_sha256": None,
                "report": None,
                "receipt": None,
            }
            data[row["id"]] = row
            return row

        async def get(self, _session, identifier, *, lock=False):
            return data.get(identifier)

        async def complete(self, _session, identifier, *, review_sha, receipt, report):
            data[identifier].update(
                review_sha256=review_sha,
                receipt=receipt,
                report=report,
                committed_at=datetime.now(UTC),
            )

        async def list_documents(self, _session, **_kwargs):
            return [
                {k: row[k] for k in ("id", "file_name", "sha256", "created_at", "committed_at")}
                for row in data.values()
            ]

    writer = AsyncMock(return_value=SimpleNamespace(inserted=1, updated=0, unchanged=0))
    monkeypatch.setattr(routes, "documents", Documents())
    monkeypatch.setattr(
        routes,
        "labs",
        SimpleNamespace(
            import_results=writer,
            previous_result=AsyncMock(return_value=None),
        ),
    )
    monkeypatch.setattr(deps, "API_KEY", "synthetic-lab-key")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)

    async def fake_session():
        yield session

    server.app.dependency_overrides[get_session] = fake_session
    with TestClient(server.app) as client:
        yield client, writer, session, data
    server.app.dependency_overrides.clear()


HEADERS = {"x-api-key": "synthetic-lab-key", "x-file-name": "results.csv"}


def test_upload_confirm_read_export_and_retry(setup):
    client, writer, session, _ = setup
    uploaded = client.post("/api/v2/lab-imports", content=CSV, headers=HEADERS)
    assert uploaded.status_code == 201, uploaded.text
    session.rollback.reset_mock()  # Upload releases its identity lookup before extraction.
    draft = uploaded.json()
    identifier = draft["id"]
    assert writer.await_count == 0
    assert draft["rows"][0]["confirmed"] is False
    path = f"/api/v2/lab-imports/{identifier}"
    assert client.get(path + "/report", headers=HEADERS).status_code == 409
    body = {"rows": draft["rows"]}
    assert client.post(path + "/commit", json=body, headers=HEADERS).status_code == 422
    assert writer.await_count == 0
    body["rows"][0]["confirmed"] = True
    response = client.post(path + "/commit", json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert writer.await_count == 1
    saved = writer.call_args.args[1][0]
    assert saved.provenance["source_page"] == 1
    assert saved.provenance["document_id"] == identifier
    assert saved.provenance["file_sha256"] == draft["sha256"]
    assert client.post(path + "/commit", json=body, headers=HEADERS).json() == response.json()
    assert writer.await_count == 1
    report = client.get(path + "/report", headers=HEADERS).json()
    assert report["results"][0]["observation"].startswith("Below")
    assert report["results"][0]["source_ids"] == [report["sources"][0]["id"]]
    original = client.get(path + "/original", headers=HEADERS)
    assert original.content == CSV
    assert original.headers["cache-control"] == "private, no-store"
    assert "attachment" in original.headers["content-disposition"]
    body["rows"][0]["value"] = "15"
    assert client.post(path + "/commit", json=body, headers=HEADERS).status_code == 409
    assert writer.await_count == 1
    assert session.rollback.await_count == 1


def test_no_write_on_bad_or_foreign_review(setup):
    client, writer, _, _ = setup
    draft = client.post("/api/v2/lab-imports", content=CSV, headers=HEADERS).json()
    path = f"/api/v2/lab-imports/{draft['id']}/commit"
    row = {**draft["rows"][0], "confirmed": True, "unit": "mmol/L"}
    response = client.post(path, json={"rows": [row]}, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == "unit"
    row["unit"] = "ng/mL"
    row["row_id"] = "p999-l999"
    assert client.post(path, json={"rows": [row]}, headers=HEADERS).status_code == 422
    row["row_id"] = "manual-1"
    assert (
        client.post(
            path,
            json={"rows": [row], "owner_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
            headers=HEADERS,
        ).status_code
        == 403
    )
    assert writer.await_count == 0


def test_private_uploads_and_originals_require_authentication(setup):
    client, _, _, _ = setup
    assert client.post("/api/v2/lab-imports", content=CSV).status_code == 401
    draft = client.post("/api/v2/lab-imports", content=CSV, headers=HEADERS).json()
    assert client.get(f"/api/v2/lab-imports/{draft['id']}/original").status_code == 401
    for scope in ("read", "ingest"):
        principal = Principal(scope=scope, owner_id=UUID("00000000-0000-0000-0000-000000000001"))
        for method, path in (
            ("POST", "/api/v2/lab-imports"),
            ("POST", "/api/v2/lab-imports/{document_id}/commit"),
        ):
            assert not is_allowed(principal, method, path)


def test_file_limits_and_failed_storage_are_safe(setup, monkeypatch):
    client, writer, session, _ = setup
    monkeypatch.setattr(routes, "MAX_DOCUMENT_BYTES", 10)
    assert client.post("/api/v2/lab-imports", content=CSV, headers=HEADERS).status_code == 413
    assert (
        client.post(
            "/api/v2/lab-imports", content=b"x", headers={**HEADERS, "x-file-name": "../report.csv"}
        ).status_code
        == 422
    )
    monkeypatch.setattr(routes, "MAX_DOCUMENT_BYTES", 5 * 1024 * 1024)
    draft = client.post("/api/v2/lab-imports", content=CSV, headers=HEADERS).json()
    session.rollback.reset_mock()
    row = {**draft["rows"][0], "confirmed": True}
    writer.side_effect = ValueError("private diagnostic text must not be returned")
    response = client.post(
        f"/api/v2/lab-imports/{draft['id']}/commit", json={"rows": [row]}, headers=HEADERS
    )
    assert response.status_code == 422
    assert "private diagnostic text" not in response.text
    assert session.rollback.await_count == 1


def test_document_deletion_requires_exact_confirmation_and_primary_ownership(setup):
    client, _, _, _ = setup
    uploaded = client.post("/api/v2/lab-imports", content=CSV, headers=HEADERS).json()
    path = f"/api/v2/lab-imports/{uploaded['id']}"
    preview = client.get(path + "/deletion", headers=HEADERS)
    assert preview.status_code == 200
    assert preview.json()["linked_result_count"] == 0
    assert (
        client.request(
            "DELETE",
            path,
            headers=HEADERS,
            json={
                "confirmation": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            },
        ).status_code
        == 422
    )
    assert (
        client.request(
            "DELETE",
            path,
            headers=HEADERS,
            json={
                "confirmation": uploaded["id"],
                "owner_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            },
        ).status_code
        == 403
    )
    assert client.request("DELETE", path, json={"confirmation": uploaded["id"]}).status_code == 401
    response = client.request(
        "DELETE", path, headers=HEADERS, json={"confirmation": uploaded["id"]}
    )
    assert response.status_code == 200
    assert response.json()["deleted_results"] == 0
    assert client.get(path + "/original", headers=HEADERS).status_code == 404
    assert client.get(path + "/report", headers=HEADERS).status_code == 404


def test_upload_retry_keeps_one_original_and_rejects_changed_content(setup):
    client, _, _, data = setup
    from tests.test_lab_document_review import CSV

    headers = {
        "X-API-Key": "synthetic-lab-key",
        "X-File-Name": "synthetic.csv",
        "X-Upload-ID": "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
    }
    first = client.post("/api/v2/lab-imports", content=CSV, headers=headers)
    assert first.status_code == 201, first.text
    repeated = client.post("/api/v2/lab-imports", content=CSV, headers=headers)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json() == first.json()
    assert len(data) == 1
    assert (
        client.post("/api/v2/lab-imports", content=CSV + b"\n", headers=headers).status_code == 409
    )
    assert client.get("/api/v2/lab-imports?cursor=invalid", headers=headers).status_code == 422
