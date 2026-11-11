"""Private laboratory originals and atomic, replayable review receipts."""

import json
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID
from sqlalchemy import text


class LabDocumentRepository:
    @staticmethod
    def _scope(document_id: UUID) -> dict[str, str]:
        return {
            "id": str(document_id),
            "owner": str(DEFAULT_OWNER_ID),
            "workspace": str(DEFAULT_WORKSPACE_ID),
        }

    async def create(
        self,
        session: Any,
        *,
        document_id: UUID,
        file_name: str,
        media_type: str,
        sha256: str,
        content: bytes,
        extraction: dict,
    ) -> dict:
        result = await session.execute(
            text("""
            INSERT INTO lab_documents
                (id, owner_id, workspace_id, file_name, media_type, sha256, content, extraction)
            VALUES (:id, :owner, :workspace, :name, :media, :sha,
                    :content, CAST(:extraction AS JSONB))
            RETURNING *
        """),
            {
                **self._scope(document_id),
                "name": file_name,
                "media": media_type,
                "sha": sha256,
                "content": content,
                "extraction": json.dumps(extraction),
            },
        )
        return dict(result.mappings().one())

    async def get(self, session: Any, document_id: UUID, *, lock: bool = False) -> dict | None:
        query = """SELECT * FROM lab_documents
            WHERE id = :id AND owner_id = :owner AND workspace_id = :workspace"""
        if lock:
            query += " FOR UPDATE"
        result = await session.execute(text(query), self._scope(document_id))
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def complete(
        self, session: Any, document_id: UUID, *, review_sha: str, receipt: dict, report: dict
    ) -> None:
        await session.execute(
            text("""
            UPDATE lab_documents SET committed_at = now(), review_sha256 = :review_sha,
                receipt = CAST(:receipt AS JSONB), report = CAST(:report AS JSONB)
            WHERE id = :id AND owner_id = :owner AND workspace_id = :workspace
                AND committed_at IS NULL
        """),
            {
                **self._scope(document_id),
                "review_sha": review_sha,
                "receipt": json.dumps(receipt),
                "report": json.dumps(report),
            },
        )

    async def list_documents(self, session: Any) -> list[dict]:
        result = await session.execute(
            text("""
            SELECT id, file_name, sha256, created_at, committed_at
            FROM lab_documents WHERE owner_id = :owner AND workspace_id = :workspace
            ORDER BY created_at DESC LIMIT 100
        """),
            {"owner": str(DEFAULT_OWNER_ID), "workspace": str(DEFAULT_WORKSPACE_ID)},
        )
        return [dict(row) for row in result.mappings().all()]


default_repository = LabDocumentRepository()
