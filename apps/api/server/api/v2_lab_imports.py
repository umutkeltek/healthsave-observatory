"""Authenticated local document extraction and explicitly confirmed imports."""

import asyncio
import hashlib
import json
import re
from dataclasses import fields, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote
from uuid import UUID

from analysis.statistical.lab_reports import LabHistoryPoint, build_report
from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from contracts.lab_imports import (
    LabImportCatalog,
    LabImportDeletion,
    LabImportDeletionPreview,
    LabImportDeletionReceipt,
    LabImportDraft,
    LabImportIndex,
    LabImportReceipt,
    LabImportReport,
    LabImportReview,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from normalization.lab_documents import MAX_DOCUMENT_BYTES, extract_document, validate_review
from normalization.labs import LABS_CSV_PLUGIN, MARKER_CATALOG, LabCsvValidationError
from starlette.concurrency import run_in_threadpool
from storage.document_pages import PAGE_SIZE, decode_cursor, next_cursor
from storage.timescale.lab_documents import default_repository as documents
from storage.timescale.labs import (
    LabResultWrite,
    is_transient_db_error,
)
from storage.timescale.labs import (
    default_repository as labs,
)

from .deps import get_session, verify_api_key
from .upload_identity import upload_id, verify_retry


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/api/v2/lab-imports", dependencies=[Depends(verify_api_key), Depends(private_response)]
)
_extraction_slots = asyncio.Semaphore(2)
_WRITE_FIELDS = tuple(f.name for f in fields(LabResultWrite))


def _draft(row: dict) -> LabImportDraft:
    extraction = row["extraction"]
    return LabImportDraft(
        id=row["id"],
        file_name=row["file_name"],
        sha256=row["sha256"],
        created_at=row["created_at"],
        status="committed" if row["committed_at"] else "draft",
        pages=extraction["pages"],
        rows=extraction["rows"],
        warnings=extraction["warnings"],
    )


async def _get(session: Any, document_id: UUID, *, lock: bool = False) -> dict:
    row = await documents.get(session, document_id, lock=lock)
    if row is None:
        raise HTTPException(404, "This lab document was not found.")
    return row


def _storage_failure(exc: Exception) -> HTTPException:
    if is_transient_db_error(exc):
        return HTTPException(503, "The private store is temporarily unavailable. Try again.")
    return HTTPException(422, "The document could not be saved. No results were imported.")


@router.get("", response_model=LabImportIndex)
async def index(session: Any = Depends(get_session), cursor: str | None = None) -> LabImportIndex:
    try:
        before = decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rows = await documents.list_documents(session, before=before)
    return LabImportIndex(documents=rows[:PAGE_SIZE], next_cursor=next_cursor(rows))


@router.get("/catalog", response_model=LabImportCatalog)
async def catalog() -> LabImportCatalog:
    return LabImportCatalog(
        markers=[
            {"loinc": m.loinc, "name": m.name, "unit": m.canonical_unit}
            for m in MARKER_CATALOG.values()
        ]
    )


@router.post("", response_model=LabImportDraft, status_code=201)
async def upload(request: Request, session: Any = Depends(get_session)) -> LabImportDraft:
    # Bound the stream even when Content-Length is absent or dishonest.
    name = unquote(request.headers.get("x-file-name", ""))
    if not name or len(name) > 180 or re.search(r"[\x00-\x1f\x7f/\\]", name):
        raise HTTPException(422, "Supply a simple CSV or PDF file name.")
    if not name.lower().endswith((".csv", ".pdf")):
        raise HTTPException(422, "Choose a CSV or PDF file.")
    identifier = upload_id(request)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, "Choose a file no larger than 5 MB.")
        content.extend(chunk)
    expected = {"file_name": name, "sha256": hashlib.sha256(content).hexdigest()}
    existing = await documents.get(session, identifier)
    if existing:
        verify_retry(existing, **expected)
        return _draft(existing)
    await session.rollback()
    if _extraction_slots.locked():
        raise HTTPException(429, "Two documents are already being read. Try again shortly.")
    try:
        async with _extraction_slots:
            extracted = await run_in_threadpool(extract_document, bytes(content), name)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    extraction = {
        "pages": [p.model_dump() for p in extracted.pages],
        "rows": [r.model_dump() for r in extracted.rows],
        "warnings": extracted.warnings,
        "evidence": extracted.evidence,
    }
    try:
        row = await documents.create(
            session,
            document_id=identifier,
            file_name=name,
            media_type="application/pdf" if name.lower().endswith(".pdf") else "text/csv",
            sha256=expected["sha256"],
            content=bytes(content),
            extraction=extraction,
        )
        if row is None:
            row = await documents.get(session, identifier)
            verify_retry(row, **expected)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise _storage_failure(exc) from exc
    return _draft(row)


@router.get("/{document_id}", response_model=LabImportDraft)
async def draft(document_id: UUID, session: Any = Depends(get_session)) -> LabImportDraft:
    return _draft(await _get(session, document_id))


@router.get("/{document_id}/original")
async def original(document_id: UUID, session: Any = Depends(get_session)) -> Response:
    row = await _get(session, document_id)
    return Response(
        bytes(row["content"]),
        media_type=row["media_type"],
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(row["file_name"], safe=""),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/{document_id}/report", response_model=LabImportReport)
async def report(document_id: UUID, session: Any = Depends(get_session)) -> LabImportReport:
    row = await _get(session, document_id)
    if row["report"] is None:
        raise HTTPException(409, "Confirm this document before opening its report.")
    return LabImportReport.model_validate(row["report"])


@router.get("/{document_id}/deletion", response_model=LabImportDeletionPreview)
async def deletion_preview(
    document_id: UUID, session: Any = Depends(get_session)
) -> LabImportDeletionPreview:
    row = await _get(session, document_id)
    return LabImportDeletionPreview(
        id=document_id,
        file_name=row["file_name"],
        linked_result_count=await documents.linked_result_count(session, document_id),
    )


@router.delete("/{document_id}", response_model=LabImportDeletionReceipt)
async def delete_document(
    document_id: UUID, deletion: LabImportDeletion, session: Any = Depends(get_session)
) -> LabImportDeletionReceipt:
    if deletion.owner_id != DEFAULT_OWNER_ID or deletion.workspace_id != DEFAULT_WORKSPACE_ID:
        raise HTTPException(403, "Lab imports belong to this Observatory's primary person only.")
    if deletion.confirmation != document_id:
        raise HTTPException(422, "Confirm the exact document before deleting it.")
    try:
        await _get(session, document_id, lock=True)
        count = await documents.delete(session, document_id, delete_results=deletion.delete_results)
        await session.commit()
        return LabImportDeletionReceipt(id=document_id, deleted_results=count)
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise HTTPException(503, "The document could not be deleted. Try again.") from exc


@router.post("/{document_id}/commit", response_model=LabImportReceipt)
async def commit(
    document_id: UUID, review: LabImportReview, session: Any = Depends(get_session)
) -> LabImportReceipt:
    if review.owner_id != DEFAULT_OWNER_ID or review.workspace_id != DEFAULT_WORKSPACE_ID:
        raise HTTPException(403, "Lab imports belong to this Observatory's primary person only.")
    try:
        parsed = validate_review(review.rows)
    except LabCsvValidationError as exc:
        raise HTTPException(
            422,
            {
                "message": "Correct the highlighted results.",
                "errors": [
                    {"row": e.row - 2, "field": e.column, "message": e.message} for e in exc.errors
                ],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    digest = hashlib.sha256(
        json.dumps(review.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    try:
        row = await _get(session, document_id, lock=True)
        if row["committed_at"]:
            if row["review_sha256"] != digest:
                raise HTTPException(
                    409,
                    "This document was saved with a different review. "
                    "Import a new draft to correct it.",
                )
            return LabImportReceipt.model_validate(row["receipt"])
        evidence = row["extraction"]["evidence"]
        for reviewed in review.rows:
            if reviewed.row_id not in evidence and not re.fullmatch(
                r"manual-[a-zA-Z0-9-]{1,64}", reviewed.row_id
            ):
                raise HTTPException(422, "A reviewed row no longer matches this document.")
        results = [
            replace(
                result,
                provenance={
                    **result.provenance,
                    "document_id": str(document_id),
                    "file_name": row["file_name"],
                    "file_sha256": row["sha256"],
                    "reviewed_by_user": True,
                    **evidence.get(reviewed.row_id, {"source_page": None, "source_excerpt": None}),
                },
            )
            for result, reviewed in zip(parsed.results, review.rows, strict=True)
        ]
        history = []
        for item in results:
            previous = await labs.previous_result(
                session,
                loinc=item.loinc_code,
                stream_id=item.stream_id,
                unit=item.canonical_unit,
                before=item.specimen_at,
                excluded_dates=[
                    other.specimen_at
                    for other in results
                    if other.loinc_code == item.loinc_code and other.stream_id == item.stream_id
                ],
            )
            if previous:
                history.append(
                    LabHistoryPoint(
                        loinc=item.loinc_code,
                        lab=item.lab_name,
                        unit=item.canonical_unit,
                        specimen_at=previous["specimen_at"],
                        value=previous["value"],
                        comparator=None,
                        quality_flags=(),
                    )
                )
        summary = await labs.import_results(
            session,
            [LabResultWrite(**{k: getattr(r, k) for k in _WRITE_FIELDS}) for r in results],
            plugin_id=LABS_CSV_PLUGIN,
        )
        receipt = LabImportReceipt(
            id=document_id,
            inserted=summary.inserted,
            updated=summary.updated,
            unchanged=summary.unchanged,
            result_count=len(results),
            report_url=f"/labs/import/{document_id}/report",
        )
        saved_report = build_report(
            document_id=document_id,
            file_name=row["file_name"],
            sha256=row["sha256"],
            imported_at=datetime.now(UTC),
            results=results,
            history=history,
        )
        await documents.complete(
            session,
            document_id,
            review_sha=digest,
            receipt=receipt.model_dump(mode="json"),
            report=saved_report.model_dump(mode="json"),
        )
        await session.commit()
        return receipt
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise _storage_failure(exc) from exc
