"""Synthetic genetics against real PostgreSQL; use only an isolated test stack.

E2E_GENETICS_REFERENCE_DIR must be mounted as GENETICS_REFERENCE_DIR on the API.
It is deliberately a separate opt-in: this test replaces its synthetic index.
"""

import gzip
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from storage.clinvar_reference import ClinvarReferenceStore

from tests.test_genetic_evidence import GENOTYPES, REFERENCE

BASE = os.getenv("E2E_BASE_URL")
KEY = os.getenv("E2E_API_KEY", "")
REFERENCE_DIR = os.getenv("E2E_GENETICS_REFERENCE_DIR")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not BASE or not REFERENCE_DIR, reason="isolated genetics stack required"),
]


def test_private_genetics_versions_retention_and_cascade(tmp_path):
    store = ClinvarReferenceStore(Path(REFERENCE_DIR))
    source = tmp_path / "synthetic.vcf.gz"

    def install(content):
        source.write_bytes(gzip.compress(content, mtime=0))
        metadata = store.install(
            source, assembly="GRCh38", source_url="https://example.invalid/synthetic-reference"
        )
        store.path("GRCh38").chmod(0o644)
        # Host-created fixtures cross Docker Desktop's bind-mount boundary.
        # Wait until the API sees the replaced inode and its read permission.
        with httpx.Client(base_url=BASE, headers={"X-API-Key": KEY}) as probe:
            for _ in range(30):
                references = probe.get("/api/v2/genetics/reference").json()["references"]
                if any(item["sha256"] == metadata["sha256"] for item in references):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("The API did not observe the synthetic reference fixture")

    install(REFERENCE)
    headers = {
        "X-API-Key": KEY,
        "X-File-Name": "synthetic.vcf",
        "X-Genome-Assembly": "GRCh38",
        "X-Genetic-Consent": "accepted",
        "X-Forward-Strand": "confirmed",
    }
    with httpx.Client(base_url=BASE, headers=headers, timeout=120) as client:
        assert (
            client.post(
                "/api/v2/genetics", content=GENOTYPES, headers={"X-Genetic-Consent": ""}
            ).status_code
            == 422
        )
        retry_headers = {"X-Upload-ID": str(uuid4())}
        default = client.post("/api/v2/genetics", content=GENOTYPES, headers=retry_headers)
        assert default.status_code == 201, default.text
        plain = default.json()
        retry = client.post("/api/v2/genetics", content=GENOTYPES, headers=retry_headers)
        assert retry.status_code == 201, retry.text
        assert retry.json() == plain
        assert (
            client.post(
                "/api/v2/genetics", content=GENOTYPES + b"\n", headers=retry_headers
            ).status_code
            == 409
        )
        plain_id = plain["document"]["id"]
        assert not plain["document"]["original_retained"]
        assert client.get(f"/api/v2/genetics/{plain_id}/original").status_code == 409
        response = client.post(
            "/api/v2/genetics", content=GENOTYPES, headers={"X-Retain-Original": "true"}
        )
        assert response.status_code == 201, response.text
        detail = response.json()
        identifier = detail["document"]["id"]
        path = f"/api/v2/genetics/{identifier}"
        original_report = detail["report"]
        assert original_report["matched_loci"] == 2
        assert client.get(path + "/original").content == GENOTYPES
        assert client.post(path + "/reanalyze", json={"confirmed": True}).json() == original_report
        assert len(client.get(path).json()["reports"]) == 1
        install(
            REFERENCE.replace(b"2026-11-08", b"2026-11-09").replace(
                b"CLNSIG=Pathogenic;", b"CLNSIG=Uncertain_significance;"
            )
        )
        updated = client.post(path + "/reanalyze", json={"confirmed": True})
        assert updated.status_code == 200, updated.text
        assert updated.json()["id"] != original_report["id"]
        assert len(client.get(path).json()["reports"]) == 2
        assert client.get(path + f"/reports/{original_report['id']}").json() == original_report
        assert (
            client.get(f"/api/v2/genetics/{plain_id}/reports/{original_report['id']}").status_code
            == 404
        )
        removed = client.request("DELETE", path + "/original", json={"confirmation": identifier})
        assert removed.status_code == 200, removed.text
        assert not removed.json()["original_retained"]
        assert client.get(path + "/original").status_code == 409
        assert client.post(path + "/reanalyze", json={"confirmed": True}).status_code == 409
        assert len(client.get(path).json()["reports"]) == 2
        deleted = client.request("DELETE", path, json={"confirmation": identifier})
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_reports"] == 2
        assert client.get(path).status_code == 404
        assert client.get(path + f"/reports/{original_report['id']}").status_code == 404
        # Keep one explicitly synthetic report for subsequent read-only browser verification.
        (tmp_path / "document-id").write_text(plain_id)
        print(f"Synthetic browser record: {plain_id}")
