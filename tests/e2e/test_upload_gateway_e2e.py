"""Opt-in proof through real TLS nginx, Next.js session/proxy, API and database."""

import os
from uuid import uuid4

import httpx
import pytest

from tests.test_genetic_evidence import GENOTYPES

BASE = os.getenv("E2E_UPLOAD_GATEWAY_URL")
PASSWORD = os.getenv("E2E_UPLOAD_WEB_PASSWORD")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not BASE or not PASSWORD, reason="isolated TLS upload gateway required"),
]


def test_gateway_preserves_session_origin_upload_size_and_retry_identity():
    # The isolated gateway uses its own synthetic, self-signed certificate.
    with httpx.Client(base_url=BASE, verify=False, timeout=120) as client:
        for route in ("lab-imports", "genetics"):
            assert client.get(f"/api/{route}").status_code == 401
        login = client.post("/auth/login", data={"password": PASSWORD}, headers={"Origin": BASE})
        assert login.status_code == 303, login.text
        assert client.get("/api/genetics/reference").status_code == 200
        assert (
            client.post(
                "/api/genetics", content=b"x", headers={"Origin": "https://other.invalid"}
            ).status_code
            == 403
        )
        identifier = str(uuid4())
        # More than the old 16 MiB nginx/API cap and Next's default 10 MiB cap.
        padding = b"# synthetic upload-size check\n" * 620_000
        content = GENOTYPES + padding
        assert 16 * 1024 * 1024 < len(content) < 50 * 1024 * 1024
        headers = {
            "Origin": BASE,
            "X-File-Name": "synthetic-large.vcf",
            "X-Upload-ID": identifier,
            "X-Genome-Assembly": "GRCh38",
            "X-Genetic-Consent": "accepted",
            "X-Forward-Strand": "confirmed",
        }
        try:
            response = client.post("/api/genetics", content=content, headers=headers)
            assert response.status_code == 201, response.text
            assert response.headers["cache-control"] == "private, no-store"
            assert response.json()["document"]["id"] == identifier
            retry = client.post("/api/genetics", content=content, headers=headers)
            assert retry.status_code == 201, retry.text
            assert retry.json() == response.json()
            assert client.get(f"/api/genetics/{identifier}/original").status_code == 409
        finally:
            client.request(
                "DELETE",
                f"/api/genetics/{identifier}",
                json={"confirmation": identifier},
                headers={"Origin": BASE},
            )
        # Lab upload is routed to Next too, and returns an editable draft.
        identifier = str(uuid4())
        try:
            response = client.post(
                "/api/lab-imports",
                headers={"Origin": BASE, "X-File-Name": "synthetic.csv", "X-Upload-ID": identifier},
                content=b"specimen_datetime,loinc,value,unit\n2026-01-01,2276-4,12,ng/mL\n",
            )
            assert response.status_code == 201, response.text
            assert response.json()["rows"][0]["confirmed"] is False
            assert client.get("/api/lab-imports?cursor=invalid").status_code == 422
            assert client.get("/api/genetics?cursor=invalid").status_code == 422
        finally:
            client.request(
                "DELETE",
                f"/api/lab-imports/{identifier}",
                json={"confirmation": identifier},
                headers={"Origin": BASE},
            )
