"""Reviewed import against a real database; use only the isolated test stack."""

import os
from uuid import uuid4

import httpx
import pytest

BASE = os.getenv("E2E_BASE_URL")
KEY = os.getenv("E2E_API_KEY", "")
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not BASE, reason="set E2E_BASE_URL")]


def test_reviewed_document_round_trip_and_idempotence():
    lab = f"Synthetic test lab {uuid4()}"
    content = (
        "specimen_datetime,loinc,value,unit,reference_low,reference_high,lab\n"
        f"2026-01-02,2276-4,12,ng/mL,20,200,{lab}\n"
    ).encode()
    with httpx.Client(base_url=BASE, headers={"X-API-Key": KEY}, timeout=120) as client:
        upload = client.post(
            "/api/v2/lab-imports", content=content, headers={"X-File-Name": "synthetic.csv"}
        )
        assert upload.status_code == 201, upload.text
        draft = upload.json()
        path = f"/api/v2/lab-imports/{draft['id']}"
        assert client.get(path + "/original").content == content
        rows = draft["rows"]
        assert client.post(path + "/commit", json={"rows": rows}).status_code == 422
        before = client.get("/api/v2/labs/2276-4")
        assert before.status_code == 404 or all(r["lab"] != lab for r in before.json()["results"])
        rows[0]["confirmed"] = True
        first = client.post(path + "/commit", json={"rows": rows})
        assert first.status_code == 200, first.text
        assert first.json()["inserted"] == 1
        assert client.post(path + "/commit", json={"rows": rows}).json() == first.json()
        report = client.get(path + "/report").json()
        assert report["results"][0]["value"] == 12
        assert report["results"][0]["source_page"] == 1
        assert report["sha256"] == draft["sha256"]
        series = client.get("/api/v2/labs/2276-4").json()["results"]
        assert len([r for r in series if r["lab"] == lab]) == 1
        # A second uploaded copy is deduped at the observation boundary.
        second = client.post(
            "/api/v2/lab-imports", content=content, headers={"X-File-Name": "same-file.csv"}
        ).json()
        rows = second["rows"]
        rows[0]["confirmed"] = True
        result = client.post(f"/api/v2/lab-imports/{second['id']}/commit", json={"rows": rows})
        assert result.status_code == 200, result.text
        assert result.json()["inserted"] == 0
        series = client.get("/api/v2/labs/2276-4").json()["results"]
        assert len([r for r in series if r["lab"] == lab]) == 1
