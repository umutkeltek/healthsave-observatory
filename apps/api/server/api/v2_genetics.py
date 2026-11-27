"""Private genotype uploads and locally matched, versioned variant evidence."""

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote
from uuid import UUID

from analysis.statistical.genetics import build_genetic_report
from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from contracts.genetics import (
    GeneticDeletion,
    GeneticDeletionReceipt,
    GeneticDocument,
    GeneticDocumentDetail,
    GeneticIndex,
    GeneticReanalysis,
    GeneticReferenceStatus,
    GeneticReferenceUpdate,
    GeneticReport,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from normalization.genotypes import ASSEMBLIES, MAX_UPLOAD, parse_genotypes
from starlette.concurrency import run_in_threadpool
from storage.clinvar_reference import ReferenceUnavailable, reference_store
from storage.document_pages import PAGE_SIZE, decode_cursor, next_cursor
from storage.timescale.genetics import default_repository as documents
from storage.timescale.labs import is_transient_db_error

from server.services import clinvar_reference as installer

from .deps import get_session, verify_api_key
from .upload_identity import upload_id, verify_retry


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(
    prefix="/api/v2/genetics", dependencies=[Depends(verify_api_key), Depends(_private)]
)
_slots = asyncio.Semaphore(1)


def _primary(body) -> None:
    if body.owner_id != DEFAULT_OWNER_ID or body.workspace_id != DEFAULT_WORKSPACE_ID:
        raise HTTPException(
            403, "Genetic records belong to this Observatory's primary person only."
        )


def _storage_error(exc: Exception) -> HTTPException:
    return HTTPException(
        503 if is_transient_db_error(exc) else 422,
        "The private genetic record could not be saved. Try again.",
    )


async def _get(session, document_id, **kwargs) -> dict:
    row = await documents.get(session, document_id, **kwargs)
    if row is None:
        raise HTTPException(404, "This genetic document was not found.")
    return row


def _compute(document_id, name, content, assembly):
    parsed = parse_genotypes(content, name, assembly=assembly, forward_strand=True)
    snapshot, records = reference_store().lookup(
        assembly, [(r.chromosome, r.position) for r in parsed.loci]
    )
    return build_genetic_report(
        document_id=document_id,
        file_name=name,
        input_sha256=hashlib.sha256(content).hexdigest(),
        parsed=parsed,
        reference=snapshot,
        records=records,
        now=datetime.now(UTC),
    )


async def _calculate(*args) -> GeneticReport:
    try:
        return await run_in_threadpool(_compute, *args)
    except ReferenceUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/reference", response_model=GeneticReferenceStatus)
async def reference_status() -> GeneticReferenceStatus:
    try:
        return GeneticReferenceStatus.model_validate(
            await run_in_threadpool(installer.status, reference_store())
        )
    except OSError as exc:
        raise HTTPException(503, "The local reference storage is unavailable.") from exc


@router.post("/reference", response_model=GeneticReferenceStatus, status_code=202)
async def update_reference(body: GeneticReferenceUpdate) -> GeneticReferenceStatus:
    _primary(body)
    if not body.confirmed:
        raise HTTPException(422, "Confirm downloading the public ClinVar reference first.")
    try:
        await run_in_threadpool(installer.start_update, reference_store(), body.assembly)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, "The reference storage directory could not be opened.") from exc
    return await reference_status()


@router.get("", response_model=GeneticIndex)
async def index(session: Any = Depends(get_session), cursor: str | None = None) -> GeneticIndex:
    try:
        before = decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rows = await documents.list(session, before=before)
    return GeneticIndex(documents=rows[:PAGE_SIZE], next_cursor=next_cursor(rows))


@router.post("", response_model=GeneticDocumentDetail, status_code=201)
async def upload(request: Request, session: Any = Depends(get_session)) -> GeneticDocumentDetail:
    if (
        request.headers.get("x-genetic-consent") != "accepted"
        or request.headers.get("x-forward-strand") != "confirmed"
    ):
        raise HTTPException(
            422,
            "Confirm ownership/permission, interpretation limits "
            "and forward-strand data before uploading.",
        )
    assembly = request.headers.get("x-genome-assembly", "")
    if assembly not in ASSEMBLIES:
        raise HTTPException(422, "Select GRCh37 or GRCh38 before uploading.")
    name = unquote(request.headers.get("x-file-name", ""))
    if not name or len(name) > 180 or re.search(r"[\x00-\x1f\x7f/\\]", name):
        raise HTTPException(422, "Supply a simple genotype file name.")
    identifier = upload_id(request)
    if _slots.locked():
        raise HTTPException(429, "A genetic file is already being processed. Try again shortly.")
    async with _slots:
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_UPLOAD:
                raise HTTPException(413, "Choose a genotype file no larger than 50 MB.")
            content.extend(chunk)
        payload = bytes(content)
        del content
        expected = {
            "file_name": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "assembly": assembly,
            "original_retained": request.headers.get("x-retain-original") == "true",
        }
        existing = await documents.get(session, identifier)
        if existing:
            verify_retry(existing, **expected)
            return await detail(identifier, session)
        await session.rollback()
        result = await _calculate(identifier, name, payload, assembly)
        try:
            created = await documents.create(
                session,
                document_id=identifier,
                file_name=name,
                sha256=result.input_sha256,
                assembly=assembly,
                content=payload if request.headers.get("x-retain-original") == "true" else None,
            )
            if created:
                await documents.add_report(session, result.model_dump(mode="json"))
            else:
                verify_retry(await documents.get(session, identifier), **expected)
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            raise _storage_error(exc) from exc
    return await detail(identifier, session)


@router.get("/{document_id}", response_model=GeneticDocumentDetail)
async def detail(document_id: UUID, session: Any = Depends(get_session)) -> GeneticDocumentDetail:
    row = await _get(session, document_id)
    versions = await documents.reports(session, document_id)
    if not versions:
        raise HTTPException(409, "This document has no completed evidence report.")
    report = await documents.report(session, document_id, versions[0]["id"])
    return GeneticDocumentDetail(
        document=GeneticDocument.model_validate(row), report=report, reports=versions
    )


@router.get("/{document_id}/reports/{report_id}", response_model=GeneticReport)
async def report_version(
    document_id: UUID, report_id: UUID, session: Any = Depends(get_session)
) -> GeneticReport:
    report = await documents.report(session, document_id, report_id)
    if report is None:
        raise HTTPException(404, "This report version was not found.")
    return GeneticReport.model_validate(report)


@router.get("/{document_id}/original")
async def original(document_id: UUID, session: Any = Depends(get_session)) -> Response:
    row = await _get(session, document_id, content=True)
    if row["source_content"] is None:
        raise HTTPException(409, "Original retention was not enabled for this document.")
    return Response(
        bytes(row["source_content"]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(row["file_name"], safe=""),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.post("/{document_id}/reanalyze", response_model=GeneticReport)
async def reanalyze(
    document_id: UUID, body: GeneticReanalysis, session: Any = Depends(get_session)
) -> GeneticReport:
    _primary(body)
    if not body.confirmed:
        raise HTTPException(
            422, "Confirm reanalysis using the currently installed public reference."
        )
    if _slots.locked():
        raise HTTPException(429, "A genetic file is already being processed. Try again shortly.")
    async with _slots:
        try:
            row = await _get(session, document_id, content=True, lock=True)
            if row["source_content"] is None:
                raise HTTPException(
                    409, "This original was not retained. Upload it again to create a new report."
                )
            report = await _calculate(
                document_id, row["file_name"], bytes(row["source_content"]), row["assembly"]
            )
            await documents.add_report(session, report.model_dump(mode="json"))
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            raise _storage_error(exc) from exc
    return await report_version(document_id, report.id, session)


@router.delete("/{document_id}/original", response_model=GeneticDocument)
async def discard_original(
    document_id: UUID, body: GeneticDeletion, session: Any = Depends(get_session)
) -> GeneticDocument:
    _primary(body)
    if body.confirmation != document_id:
        raise HTTPException(422, "Confirm the exact document before removing its original.")
    try:
        await _get(session, document_id, lock=True)
        await documents.discard_original(session, document_id)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise HTTPException(503, "The retained original could not be removed. Try again.") from exc
    return GeneticDocument.model_validate(await _get(session, document_id))


@router.delete("/{document_id}", response_model=GeneticDeletionReceipt)
async def delete_document(
    document_id: UUID, body: GeneticDeletion, session: Any = Depends(get_session)
) -> GeneticDeletionReceipt:
    _primary(body)
    if body.confirmation != document_id:
        raise HTTPException(422, "Confirm the exact genetic document before deleting it.")
    try:
        await _get(session, document_id, lock=True)
        count = await documents.delete(session, document_id)
        await session.commit()
        return GeneticDeletionReceipt(id=document_id, deleted_reports=count)
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise HTTPException(503, "The genetic document could not be deleted. Try again.") from exc
