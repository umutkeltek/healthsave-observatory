"""Explicit public-data downloads. This module never accepts user genotypes."""

import fcntl
import json
import tempfile
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from contracts.genetics import GeneticReferenceJob
from storage.clinvar_reference import ClinvarReferenceStore, ReferenceUnavailable

MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_SECONDS = 15 * 60


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("The public reference URL redirected unexpectedly.")


def _write_status(root: Path, status: dict) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="status-", suffix=".json", dir=root, delete=False
    ) as handle:
        json.dump(status, handle)
        name = handle.name
    Path(name).replace(root / "install-status.json")


def _busy(root: Path) -> bool:
    if not (root / "install.lock").exists():
        return False
    with (root / "install.lock").open("r+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def status(store: ClinvarReferenceStore) -> dict:
    job = {"state": "idle"}
    state_file = store.root / "install-status.json"
    if state_file.exists():
        try:
            job = GeneticReferenceJob.model_validate_json(state_file.read_text()).model_dump()
        except (ValueError, OSError):
            job = {
                "state": "interrupted",
                "message": "The reference update status is unavailable. You can retry the update.",
            }
    if job.get("state") in ("downloading", "indexing") and not _busy(store.root):
        job = {
            **job,
            "state": "interrupted",
            "message": "The update was interrupted. "
            "Any complete installed reference remains available; retry to finish.",
        }
    references = []
    for assembly in ("GRCh37", "GRCh38"):
        try:
            metadata = store.metadata(assembly)
            if metadata:
                references.append(metadata)
        except ReferenceUnavailable:
            job = {
                "state": "failed",
                "message": "A reference index is unreadable. Install that assembly again.",
            }
    return {"references": references, "job": job}


def start_update(store: ClinvarReferenceStore, assembly: str) -> None:
    store.path(assembly)  # Validate before constructing a URL or touching disk.
    store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (store.root / "install.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("A public reference update is already running.") from None
    job = {
        "state": "downloading",
        "assembly": assembly,
        "message": "Downloading public ClinVar data. No personal data is sent.",
        "started_at": datetime.now(UTC).isoformat(),
        "bytes_downloaded": 0,
        "records_indexed": 0,
    }
    try:
        _write_status(store.root, job)
        thread = threading.Thread(target=_update, args=(store, assembly, lock, job), daemon=True)
        thread.start()
    except Exception:
        lock.close()
        raise


def _update(store: ClinvarReferenceStore, assembly: str, lock, job: dict) -> None:
    source = None
    started = time.monotonic()
    url = f"https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_{assembly}/clinvar.vcf.gz"
    try:
        # Only orphaned temporary files owned by this installer are removed;
        # the process-wide update lock excludes a live competing update.
        for pattern in ("download-*.vcf.gz", "reference-*.sqlite", "status-*.json"):
            for orphan in store.root.glob(pattern):
                orphan.unlink(missing_ok=True)
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(
            urllib.request.Request(
                url, headers={"User-Agent": "HealthSave-Observatory/ClinVar-reference"}
            ),
            timeout=30,
        ) as response:
            if int(response.headers.get("Content-Length", 0)) > MAX_DOWNLOAD:
                raise ValueError("Public reference exceeds the download size limit.")
            with tempfile.NamedTemporaryFile(
                prefix="download-", suffix=".vcf.gz", dir=store.root, delete=False
            ) as handle:
                source = Path(handle.name)
                last_progress = 0
                while chunk := response.read(1024 * 1024):
                    job["bytes_downloaded"] += len(chunk)
                    if (
                        job["bytes_downloaded"] > MAX_DOWNLOAD
                        or time.monotonic() - started > MAX_SECONDS
                    ):
                        raise ValueError("Reference download exceeded its size or time limit.")
                    handle.write(chunk)
                    if job["bytes_downloaded"] - last_progress >= 4 * 1024 * 1024:
                        _write_status(store.root, job)
                        last_progress = job["bytes_downloaded"]
        job.update(state="indexing", message="Indexing public single-nucleotide evidence locally.")
        _write_status(store.root, job)

        def progress(count):
            if time.monotonic() - started > MAX_SECONDS:
                raise ValueError("Reference indexing exceeded its time limit.")
            job["records_indexed"] = count
            _write_status(store.root, job)

        metadata = store.install(
            source,
            assembly=assembly,
            source_url=url,
            progress=progress,
            deadline=started + MAX_SECONDS,
        )
        job.update(
            state="complete",
            records_indexed=metadata["record_count"],
            message="Public reference installed. "
            "Existing reports keep their original evidence version.",
        )
    except Exception:
        job.update(
            state="failed",
            message="The public reference update failed. "
            "Any complete installed index is preserved. "
            "Check connectivity and disk space, then retry.",
        )
    finally:
        try:
            if source:
                source.unlink(missing_ok=True)
            _write_status(store.root, job)
        finally:
            lock.close()
