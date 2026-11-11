"""Retry and history regressions against an explicitly configured isolated database."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from storage.timescale.genetics import GeneticRepository
from storage.timescale.lab_documents import LabDocumentRepository

BASE = os.getenv("E2E_BASE_URL")
DATABASE = os.getenv("E2E_DATABASE_URL")
KEY = os.getenv("E2E_API_KEY", "")
OWNER = "00000000-0000-0000-0000-000000000001"
WORKSPACE = "00000000-0000-0000-0000-000000000001"
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not BASE or not DATABASE, reason="isolated API and database required"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["labs", "genetics"])
async def test_history_pages_keep_equal_timestamps_and_survive_deleted_cursor(kind):
    table, route = (
        ("lab_documents", "lab-imports") if kind == "labs" else ("genetic_documents", "genetics")
    )
    connection = await asyncpg.connect(DATABASE)
    ids = [uuid4() for _ in range(105)]
    foreign_id = uuid4()
    created = datetime(2099, 1, 1, tzinfo=UTC)
    try:
        for identifier in [*ids, foreign_id]:
            owner = OWNER if identifier != foreign_id else str(uuid4())
            if kind == "labs":
                await connection.execute(
                    """INSERT INTO lab_documents
                    (id, owner_id, workspace_id, file_name, media_type, sha256,
                     content, extraction, created_at)
                    VALUES ($1, $2, $3, 'synthetic-page.csv', 'text/csv',
                            'synthetic', 'x', '{}', $4)""",
                    identifier,
                    owner,
                    WORKSPACE,
                    created,
                )
            else:
                await connection.execute(
                    """INSERT INTO genetic_documents
                    (id, owner_id, workspace_id, file_name, sha256, assembly, created_at)
                    VALUES ($1, $2, $3, 'synthetic-page.vcf', 'synthetic', 'GRCh38', $4)""",
                    identifier,
                    owner,
                    WORKSPACE,
                    created,
                )
        async with httpx.AsyncClient(base_url=BASE, headers={"X-API-Key": KEY}) as client:
            response = await client.get(f"/api/v2/{route}")
            assert response.status_code == 200, response.text
            first = response.json()
            first_ids = [item["id"] for item in first["documents"]]
            expected = sorted((str(identifier) for identifier in ids), reverse=True)
            assert first_ids == expected[:100]
            assert first["next_cursor"]
            # Keyset pagination does not require the cursor row to still exist.
            await connection.execute(f"DELETE FROM {table} WHERE id = $1", first_ids[-1])
            response = await client.get(f"/api/v2/{route}", params={"cursor": first["next_cursor"]})
            assert response.status_code == 200, response.text
            second_ids = [item["id"] for item in response.json()["documents"]]
            assert second_ids[:5] == expected[100:]
            assert not set(first_ids).intersection(second_ids)
            assert str(foreign_id) not in first_ids + second_ids
    finally:
        await connection.execute(
            f"DELETE FROM {table} WHERE id = ANY($1::uuid[])", [*ids, foreign_id]
        )
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["labs", "genetics"])
async def test_racing_document_inserts_have_exactly_one_winner(kind):
    engine = create_async_engine(DATABASE.replace("postgresql://", "postgresql+asyncpg://", 1))
    identifier = uuid4()
    repository = LabDocumentRepository() if kind == "labs" else GeneticRepository()
    table = "lab_documents" if kind == "labs" else "genetic_documents"
    connection = await asyncpg.connect(DATABASE)

    async def insert():
        async with AsyncSession(engine) as session:
            fields = dict(
                document_id=identifier, file_name="synthetic.csv", sha256="synthetic", content=b"x"
            )
            fields.update(
                {"media_type": "text/csv", "extraction": {}}
                if kind == "labs"
                else {"assembly": "GRCh38"}
            )
            result = await repository.create(session, **fields)
            await session.commit()
            return bool(result)

    try:
        assert sorted(await asyncio.gather(insert(), insert())) == [False, True]
        assert (
            await connection.fetchval(f"SELECT count(*) FROM {table} WHERE id = $1", identifier)
            == 1
        )
    finally:
        await connection.execute(f"DELETE FROM {table} WHERE id = $1", identifier)
        await connection.close()
        await engine.dispose()


def test_lab_upload_retry_returns_the_original_record_and_rejects_changed_bytes():
    identifier = str(uuid4())
    headers = {"X-API-Key": KEY, "X-File-Name": "synthetic-retry.csv", "X-Upload-ID": identifier}
    content = b"specimen_datetime,loinc,value,unit\n2026-01-01,2276-4,12,ng/mL\n"
    with httpx.Client(base_url=BASE, headers=headers) as client:
        try:
            first = client.post("/api/v2/lab-imports", content=content)
            assert first.status_code == 201, first.text
            retry = client.post("/api/v2/lab-imports", content=content)
            assert retry.status_code == 201, retry.text
            assert retry.json() == first.json()
            assert client.post("/api/v2/lab-imports", content=content + b"\n").status_code == 409
        finally:
            client.request(
                "DELETE", f"/api/v2/lab-imports/{identifier}", json={"confirmation": identifier}
            )
