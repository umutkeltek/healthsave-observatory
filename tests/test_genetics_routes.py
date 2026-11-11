from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import server
from fastapi.testclient import TestClient
from server.api import deps
from server.api import v2_genetics as routes
from server.api.access import Principal, is_allowed
from server.api.deps import get_session

from tests.test_genetic_evidence import GENOTYPES, install_reference

HEADERS = {
    "X-API-Key": "synthetic-genetic-key",
    "X-File-Name": "synthetic.vcf",
    "X-Genome-Assembly": "GRCh38",
    "X-Genetic-Consent": "accepted",
    "X-Forward-Strand": "confirmed",
}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    store, _, _ = install_reference(tmp_path)
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    data, reports = {}, {}

    class Documents:
        async def create(self, _session, *, document_id, file_name, sha256, assembly, content):
            data[document_id] = {
                "id": document_id,
                "file_name": file_name,
                "sha256": sha256,
                "assembly": assembly,
                "source_content": content,
                "original_retained": content is not None,
                "created_at": datetime.now(UTC),
            }

            return True

        async def get(self, _session, identifier, **_kwargs):
            row = data.get(identifier)
            if row is None:
                return None
            return (
                dict(row)
                if _kwargs.get("content")
                else {k: v for k, v in row.items() if k != "source_content"}
            )

        async def list(self, _session, **_kwargs):
            return [
                {k: v for k, v in row.items() if k != "source_content"} for row in data.values()
            ]

        async def add_report(self, _session, report):
            reports.setdefault(UUID(report["id"]), report)

        async def report(self, _session, identifier, report_id):
            report = reports.get(report_id)
            return report if report and report["document_id"] == str(identifier) else None

        async def reports(self, _session, identifier):
            return [
                {
                    "id": UUID(r["id"]),
                    "created_at": r["created_at"],
                    "reference_release": r["reference"]["release_date"],
                    "engine_version": r["engine_version"],
                }
                for r in reports.values()
                if r["document_id"] == str(identifier)
            ]

        async def delete(self, _session, identifier):
            del data[identifier]
            keys = [
                key for key, report in reports.items() if report["document_id"] == str(identifier)
            ]
            for key in keys:
                del reports[key]
            return len(keys)

        async def discard_original(self, _session, identifier):
            data[identifier]["source_content"] = None
            data[identifier]["original_retained"] = False

    monkeypatch.setattr(routes, "documents", Documents())
    monkeypatch.setattr(routes, "reference_store", lambda: store)
    monkeypatch.setattr(deps, "API_KEY", "synthetic-genetic-key")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)

    async def fake_session():
        yield session

    server.app.dependency_overrides[get_session] = fake_session
    try:
        with TestClient(server.app) as client:
            yield client, data, reports, session
    finally:
        server.app.dependency_overrides.clear()


def test_private_report_defaults_to_no_retained_original_and_requires_consent(setup):
    client, data, _, _ = setup
    assert client.post("/api/v2/genetics", content=GENOTYPES).status_code == 401
    assert (
        client.post(
            "/api/v2/genetics", content=GENOTYPES, headers={**HEADERS, "X-Genetic-Consent": ""}
        ).status_code
        == 422
    )
    assert not data
    response = client.post("/api/v2/genetics", content=GENOTYPES, headers=HEADERS)
    assert response.status_code == 201, response.text
    detail = response.json()
    path = f"/api/v2/genetics/{detail['document']['id']}"
    assert detail["report"]["matched_loci"] == 2
    assert not detail["document"]["original_retained"]
    assert next(iter(data.values()))["source_content"] is None
    assert client.get(path, headers=HEADERS).headers["cache-control"] == "private, no-store"
    assert client.get(path + "/original", headers=HEADERS).status_code == 409
    assert (
        client.post(path + "/reanalyze", headers=HEADERS, json={"confirmed": True}).status_code
        == 409
    )


def test_retained_original_reanalysis_is_idempotent_and_deletion_removes_versions(setup):
    client, _, reports, _ = setup
    detail = client.post(
        "/api/v2/genetics", content=GENOTYPES, headers={**HEADERS, "X-Retain-Original": "true"}
    ).json()
    identifier = detail["document"]["id"]
    path = f"/api/v2/genetics/{identifier}"
    assert client.get(path + "/original", headers=HEADERS).content == GENOTYPES
    repeated = client.post(path + "/reanalyze", headers=HEADERS, json={"confirmed": True})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == detail["report"]
    assert len(reports) == 1
    assert (
        client.request(
            "DELETE",
            path,
            headers=HEADERS,
            json={"confirmation": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        ).status_code
        == 422
    )
    deleted = client.request("DELETE", path, headers=HEADERS, json={"confirmation": identifier})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_reports"] == 1
    assert (
        client.get(path + f"/reports/{detail['report']['id']}", headers=HEADERS).status_code == 404
    )
    assert client.get(path + "/original", headers=HEADERS).status_code == 404


def test_participant_keys_cannot_access_genetic_data_or_reference_management(setup):
    for scope in ("read", "ingest"):
        principal = Principal(scope=scope, owner_id=UUID("00000000-0000-0000-0000-000000000001"))
        for method, path in (
            ("GET", "/api/v2/genetics"),
            ("POST", "/api/v2/genetics"),
            ("POST", "/api/v2/genetics/reference"),
            ("DELETE", "/api/v2/genetics/{document_id}"),
        ):
            assert not is_allowed(principal, method, path)


def test_removing_original_keeps_reports_and_blocks_reanalysis(setup):
    client, data, reports, _ = setup
    detail = client.post(
        "/api/v2/genetics", content=GENOTYPES, headers={**HEADERS, "X-Retain-Original": "true"}
    ).json()
    identifier = detail["document"]["id"]
    path = f"/api/v2/genetics/{identifier}"
    removed = client.request(
        "DELETE", path + "/original", headers=HEADERS, json={"confirmation": identifier}
    )
    assert removed.status_code == 200, removed.text
    assert not removed.json()["original_retained"]
    assert data[UUID(identifier)]["source_content"] is None
    assert len(reports) == 1
    assert client.get(path, headers=HEADERS).json()["report"] == detail["report"]
    assert (
        client.post(path + "/reanalyze", headers=HEADERS, json={"confirmed": True}).status_code
        == 409
    )
    assert client.get(path + "/original", headers=HEADERS).status_code == 409


def test_foreign_owner_invalid_build_and_missing_record_are_rejected(setup):
    client, data, _, _ = setup
    response = client.post(
        "/api/v2/genetics", content=GENOTYPES, headers={**HEADERS, "X-Genome-Assembly": "GRCh37"}
    )
    assert response.status_code == 422
    assert not data
    response = client.post(
        "/api/v2/genetics/reference",
        headers=HEADERS,
        json={
            "assembly": "GRCh38",
            "confirmed": True,
            "owner_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        },
    )
    assert response.status_code == 403
    assert (
        client.get(
            "/api/v2/genetics/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", headers=HEADERS
        ).status_code
        == 404
    )


def test_upload_identity_retries_without_duplicate_reports_and_rejects_reuse(setup):
    client, data, reports, _ = setup
    identifier = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    headers = {**HEADERS, "X-Upload-ID": identifier}
    first = client.post("/api/v2/genetics", content=GENOTYPES, headers=headers)
    assert first.status_code == 201, first.text
    again = client.post("/api/v2/genetics", content=GENOTYPES, headers=headers)
    assert again.status_code == 201, again.text
    assert again.json() == first.json()
    assert len(data) == len(reports) == 1
    changed = client.post("/api/v2/genetics", content=GENOTYPES + b"\n", headers=headers)
    assert changed.status_code == 409
    assert (
        client.post(
            "/api/v2/genetics", content=GENOTYPES, headers={**headers, "X-Retain-Original": "true"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v2/genetics", content=GENOTYPES, headers={**HEADERS, "X-Upload-ID": "invalid"}
        ).status_code
        == 422
    )
    assert client.get("/api/v2/genetics?cursor=invalid", headers=HEADERS).status_code == 422
