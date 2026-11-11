"""Owner-scoped private originals and immutable genetic report versions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from sqlalchemy import text


def _scope(document_id: UUID | None = None) -> dict:
    return {
        "id": str(document_id) if document_id else None,
        "owner": str(DEFAULT_OWNER_ID),
        "workspace": str(DEFAULT_WORKSPACE_ID),
    }


class GeneticRepository:
    async def create(
        self,
        session: Any,
        *,
        document_id: UUID,
        file_name: str,
        sha256: str,
        assembly: str,
        content: bytes | None,
    ) -> None:
        await session.execute(
            text("""INSERT INTO genetic_documents
            (id, owner_id, workspace_id, file_name, sha256, assembly, source_content)
            VALUES (:id, :owner, :workspace, :name, :sha, :assembly, :content)"""),
            {
                **_scope(document_id),
                "name": file_name,
                "sha": sha256,
                "assembly": assembly,
                "content": content,
            },
        )

    async def get(
        self, session: Any, document_id: UUID, *, content: bool = False, lock: bool = False
    ) -> dict | None:
        columns = (
            "id, file_name, sha256, assembly, created_at, "
            "source_content IS NOT NULL AS original_retained"
        )
        if content:
            columns += ", source_content"
        result = await session.execute(
            text(
                f"""SELECT {columns} FROM genetic_documents
            WHERE id = :id AND owner_id = :owner AND workspace_id = :workspace"""
                + (" FOR UPDATE" if lock else "")
            ),
            _scope(document_id),
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def list(self, session: Any) -> list[dict]:
        result = await session.execute(
            text("""SELECT id, file_name, sha256, assembly,
            created_at, source_content IS NOT NULL AS original_retained
            FROM genetic_documents WHERE owner_id = :owner AND workspace_id = :workspace
            ORDER BY created_at DESC LIMIT 100"""),
            _scope(),
        )
        return [dict(row) for row in result.mappings().all()]

    async def add_report(self, session: Any, report: dict) -> None:
        await session.execute(
            text("""INSERT INTO genetic_reports
            (id, document_id, created_at, reference_release, engine_version, report)
            SELECT :report_id, id, :created, :release, :engine, CAST(:report AS JSONB)
            FROM genetic_documents
            WHERE id = :id AND owner_id = :owner AND workspace_id = :workspace
            ON CONFLICT (id) DO NOTHING"""),
            {
                **_scope(UUID(report["document_id"])),
                "report_id": report["id"],
                "created": datetime.fromisoformat(report["created_at"]),
                "release": report["reference"]["release_date"],
                "engine": report["engine_version"],
                "report": json.dumps(report),
            },
        )

    async def reports(self, session: Any, document_id: UUID) -> list[dict]:
        result = await session.execute(
            text("""SELECT r.id, r.created_at,
                r.reference_release, r.engine_version
            FROM genetic_reports r JOIN genetic_documents d ON d.id = r.document_id
            WHERE d.id = :id AND d.owner_id = :owner AND d.workspace_id = :workspace
            ORDER BY r.created_at DESC"""),
            _scope(document_id),
        )
        return [dict(row) for row in result.mappings().all()]

    async def report(self, session: Any, document_id: UUID, report_id: UUID) -> dict | None:
        result = await session.execute(
            text("""SELECT r.report
            FROM genetic_reports r JOIN genetic_documents d ON d.id = r.document_id
            WHERE d.id = :id AND d.owner_id = :owner AND d.workspace_id = :workspace
                AND r.id = :report_id"""),
            {**_scope(document_id), "report_id": str(report_id)},
        )
        return result.scalar_one_or_none()

    async def delete(self, session: Any, document_id: UUID) -> int:
        reports = await self.reports(session, document_id)
        await session.execute(
            text("""DELETE FROM genetic_documents
            WHERE id = :id AND owner_id = :owner AND workspace_id = :workspace"""),
            _scope(document_id),
        )
        return len(reports)

    async def discard_original(self, session: Any, document_id: UUID) -> None:
        await session.execute(
            text("""UPDATE genetic_documents SET source_content = NULL
            WHERE id = :id AND owner_id = :owner AND workspace_id = :workspace"""),
            _scope(document_id),
        )


default_repository = GeneticRepository()
