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


def test_deleting_an_older_document_preserves_a_later_correction():
    lab = f"Synthetic deletion lab {uuid4()}"
    with httpx.Client(base_url=BASE, headers={"X-API-Key": KEY}, timeout=120) as client:

        def save(value):
            raw = (
                "specimen_datetime,loinc,value,unit,reference_low,reference_high,lab\n"
                f"2026-01-02,2276-4,{value},ng/mL,20,200,{lab}\n"
            ).encode()
            upload = client.post(
                "/api/v2/lab-imports", content=raw, headers={"X-File-Name": "synthetic.csv"}
            )
            assert upload.status_code == 201, upload.text
            draft = upload.json()
            draft["rows"][0]["confirmed"] = True
            path = f"/api/v2/lab-imports/{draft['id']}"
            saved = client.post(path + "/commit", json={"rows": draft["rows"]})
            assert saved.status_code == 200, saved.text
            return draft["id"], path

        first_id, first = save(12)
        second_id, second = save(14)
        assert client.get(first + "/deletion").json()["linked_result_count"] == 0
        response = client.request(
            "DELETE", first, json={"confirmation": first_id, "delete_results": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["deleted_results"] == 0
        assert client.get(first + "/report").status_code == 404
        series = client.get("/api/v2/labs/2276-4").json()["results"]
        assert [r["value"] for r in series if r["lab"] == lab] == [14]
        assert client.get(second + "/deletion").json()["linked_result_count"] == 1
        response = client.request(
            "DELETE", second, json={"confirmation": second_id, "delete_results": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["deleted_results"] == 1
        assert client.get(second + "/original").status_code == 404


def test_reviewed_censored_correction_uses_the_next_comparable_historical_result():
    lab = f"Synthetic comparison lab {uuid4()}"
    with httpx.Client(base_url=BASE, headers={"X-API-Key": KEY}, timeout=120) as client:

        def save(entries):
            raw = (
                "specimen_datetime,loinc,value,unit,reference_low,reference_high,lab\n"
                + "".join(f"{date},2276-4,{value},ng/mL,20,200,{lab}\n" for date, value in entries)
            ).encode()
            response = client.post(
                "/api/v2/lab-imports", content=raw, headers={"X-File-Name": "synthetic.csv"}
            )
            assert response.status_code == 201, response.text
            draft = response.json()
            for row in draft["rows"]:
                row["confirmed"] = True
            path = f"/api/v2/lab-imports/{draft['id']}"
            response = client.post(path + "/commit", json={"rows": draft["rows"]})
            assert response.status_code == 200, response.text
            return client.get(path + "/report").json()

        save([("2025-11-01", "8"), ("2025-12-01", "10")])
        report = save([("2025-12-01", "<5"), ("2026-01-02", "12")])
        current = report["results"][1]
        assert current["comparison"]["previous_value"] == 8
        assert current["comparison"]["absolute_change"] == 4
        assert current["comparison"]["previous_specimen_at"].startswith("2025-11-01")


def test_precision_correction_survives_older_document_deletion_and_lab_case_is_stable():
    lab = f"Synthetic precision lab {uuid4()}"
    with httpx.Client(base_url=BASE, headers={"X-API-Key": KEY}, timeout=120) as client:

        def save(date, value, unit, name):
            content = (
                "specimen_datetime,loinc,value,unit,lab\n"
                + f"{date},3016-3,{value},{unit},{name}\n"
            ).encode()
            response = client.post(
                "/api/v2/lab-imports", content=content, headers={"X-File-Name": "synthetic.csv"}
            )
            assert response.status_code == 201, response.text
            draft = response.json()
            draft["rows"][0]["confirmed"] = True
            path = f"/api/v2/lab-imports/{draft['id']}"
            saved = client.post(path + "/commit", json={"rows": draft["rows"]})
            assert saved.status_code == 200, saved.text
            return draft["id"], path, saved.json()

        older_id, older, _ = save("2026-01-01", 2, "mIU/L", lab)
        corrected_id, corrected, saved = save("2026-01-01T00:00:00Z", 2, "mIU/L", lab.upper())
        assert saved["updated"] == 1
        assert client.get(older + "/deletion").json()["linked_result_count"] == 0
        assert client.get(corrected + "/deletion").json()["linked_result_count"] == 1
        assert (
            client.request(
                "DELETE", older, json={"confirmation": older_id, "delete_results": True}
            ).status_code
            == 200
        )
        later_id, later, _ = save("2026-02-01", 3, "m[IU]/L", lab)
        report = client.get(later + "/report").json()
        assert report["results"][0]["comparison"]["previous_value"] == 2
        assert client.get(corrected + "/report").status_code == 200
        for identifier, path in [(corrected_id, corrected), (later_id, later)]:
            assert (
                client.request(
                    "DELETE", path, json={"confirmation": identifier, "delete_results": True}
                ).status_code
                == 200
            )
