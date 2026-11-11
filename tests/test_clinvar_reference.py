"""Public-reference lifecycle; all fixtures are synthetic and contain no DNA."""

import fcntl
import gzip
import io
import json
import sqlite3
from unittest.mock import Mock

import pytest
from server.services import clinvar_reference as updater
from storage import clinvar_reference as reference

from tests.test_genetic_evidence import REFERENCE, install_reference


def test_public_get_and_failed_update_keeps_installed_index(tmp_path, monkeypatch):
    store, _, previous = install_reference(tmp_path)
    requests = []

    class PublicResponse(io.BytesIO):
        headers = {}

    def open_public(request, timeout):
        requests.append(request)
        assert timeout == 30
        return PublicResponse(gzip.compress(REFERENCE))

    monkeypatch.setattr(updater.urllib.request, "build_opener", lambda *_: Mock(open=open_public))
    lock = (store.root / "install.lock").open("a")
    job = {"state": "downloading", "assembly": "GRCh38", "bytes_downloaded": 0}
    updater._update(store, "GRCh38", lock, job)
    assert lock.closed
    assert job["state"] == "complete"
    assert (
        requests[0].full_url == "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz"
    )
    assert requests[0].get_method() == "GET"
    assert requests[0].data is None
    assert set(requests[0].headers) == {"User-agent"}
    installed = store.metadata("GRCh38")
    assert installed["record_count"] == previous["record_count"]
    monkeypatch.setattr(
        updater.urllib.request,
        "build_opener",
        lambda *_: Mock(open=Mock(side_effect=OSError("offline"))),
    )
    lock = (store.root / "install.lock").open("a")
    updater._update(store, "GRCh38", lock, dict(job, state="downloading"))
    assert updater.status(store)["job"]["state"] == "failed"
    assert store.metadata("GRCh38") == installed
    assert not list(store.root.glob("download-*"))


def test_update_lock_and_interrupted_status(tmp_path):
    store, _, _ = install_reference(tmp_path)
    with (store.root / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        updater._write_status(store.root, {"state": "indexing", "assembly": "GRCh38"})
        assert updater.status(store)["job"]["state"] == "indexing"
        with pytest.raises(ValueError, match="already running"):
            updater.start_update(store, "GRCh38")
    assert updater.status(store)["job"]["state"] == "interrupted"
    assert len(updater.status(store)["references"]) == 1
    with pytest.raises(ValueError, match="GRCh37 or GRCh38"):
        updater.start_update(store, "../../private")


def test_missing_metadata_is_unavailable_not_a_programming_error(tmp_path):
    store, _, _ = install_reference(tmp_path)
    with sqlite3.connect(store.path("GRCh38")) as conn:
        conn.execute("UPDATE metadata SET value = ?", (json.dumps({"assembly": "GRCh38"}),))
    with pytest.raises(reference.ReferenceUnavailable):
        store.metadata("GRCh38")
    with pytest.raises(reference.ReferenceUnavailable):
        store.lookup("GRCh38", [("1", 10)])
    assert updater.status(store)["job"]["state"] == "failed"


def test_candidate_limit_fails_instead_of_silently_omitting(tmp_path, monkeypatch):
    store, _, _ = install_reference(tmp_path)
    monkeypatch.setattr(reference, "MAX_REFERENCE_MATCHES", 1)
    with pytest.raises(reference.ReferenceMatchLimit, match="too many"):
        store.lookup("GRCh38", [("1", 10), ("1", 11)])


@pytest.mark.parametrize("content", ["[]", '{"state":"unknown"}', "null"])
def test_invalid_update_status_is_recoverable(tmp_path, content):
    store, _, _ = install_reference(tmp_path)
    (store.root / "install-status.json").write_text(content)
    state = updater.status(store)
    assert state["job"]["state"] == "interrupted"
    assert len(state["references"]) == 1
