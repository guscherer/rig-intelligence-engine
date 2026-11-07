"""Testes de integração do store (exigem Postgres do compose)."""

from __future__ import annotations

import os

import asyncpg  # type: ignore[import-untyped]  # asyncpg nao publica stubs tipados
import pytest

from rig.ingestion.chunker import chunk_document
from rig.ingestion.store import (
    get_cursor,
    record_ingest_run,
    update_cursor,
    upsert,
    upsert_chunks,
    upsert_document,
)

pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://rig:rig@localhost:5432/rig")
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


@pytest.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)
    except Exception as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def clean_doc(pool):
    source = "camara"
    doc_id = "test-store-999"
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chunks WHERE source=$1 AND doc_id=$2", source, doc_id)
        await conn.execute("DELETE FROM documents WHERE source=$1 AND doc_id=$2", source, doc_id)
    yield source, doc_id
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chunks WHERE source=$1 AND doc_id=$2", source, doc_id)
        await conn.execute("DELETE FROM documents WHERE source=$1 AND doc_id=$2", source, doc_id)


async def test_idempotency(pool, clean_doc):
    source, doc_id = clean_doc
    text = "Art. 1º Este é um teste.\n\nArt. 2º Segundo artigo."
    meta = {"doc_id": doc_id, "source": source, "doc_type": "proposicao"}
    chunks = chunk_document(text, meta)

    r1 = await upsert(pool, source=source, doc_id=doc_id, chunks=chunks)
    assert r1.new == 1
    assert r1.updated == 0
    assert r1.skipped == 0

    r2 = await upsert(pool, source=source, doc_id=doc_id, chunks=chunks)
    assert r2.new == 0
    assert r2.updated == 0
    assert r2.skipped == 1

    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM chunks WHERE source=$1 AND doc_id=$2", source, doc_id
        )
        assert n == len(chunks)
        run_id = await record_ingest_run(pool, source=source, scope="test", counters=r2)
        assert isinstance(run_id, int)


async def test_tsv_populated(pool, clean_doc):
    source, doc_id = clean_doc
    text = "Art. 1º Texto para busca."
    meta = {"doc_id": doc_id, "source": source, "doc_type": "proposicao"}
    chunks = chunk_document(text, meta)
    await upsert(pool, source=source, doc_id=doc_id, chunks=chunks)
    async with pool.acquire() as conn:
        tsv = await conn.fetchval(
            "SELECT tsv FROM chunks WHERE source=$1 AND doc_id=$2 LIMIT 1",
            source,
            doc_id,
        )
        assert tsv is not None


async def test_cursor_roundtrip(pool):
    source = "camara"
    scope = "test-cursor"
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ingest_cursor WHERE source=$1 AND scope=$2", source, scope)
    assert await get_cursor(pool, source, scope) is None
    await update_cursor(pool, source, scope, last_id="42", last_ts=None)
    cur = await get_cursor(pool, source, scope)
    assert cur is not None
    assert cur["last_id"] == "42"
    await update_cursor(pool, source, scope, last_id="43")
    cur2 = await get_cursor(pool, source, scope)
    assert cur2["last_id"] == "43"
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ingest_cursor WHERE source=$1 AND scope=$2", source, scope)


async def test_hierarchy_to_dict_branch(pool, clean_doc):
    source, doc_id = clean_doc

    class H:
        def to_dict(self):
            return {"artigo": "1"}

    await upsert_document(pool, source=source, doc_id=doc_id, content_hash="sha256:x")
    chunk = {
        "chunk_id": f"{doc_id}-h",
        "source": source,
        "doc_id": doc_id,
        "doc_type": "proposicao",
        "doc_meta": {},
        "breadcrumb": "b",
        "hierarchy": H(),
        "kind": "dispositivo",
        "chunk_text": "hi",
        "text": "hi",
        "ordinal": 1,
        "char_span": None,
        "page": None,
        "extraction_quality": "high",
        "content_hash": "sha256:ch",
    }
    # fix key name expected by _chunk_text
    chunk["chunk_text"] = "hi"
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[chunk])
    async with pool.acquire() as conn:
        h = await conn.fetchval("SELECT hierarchy FROM chunks WHERE chunk_id=$1", chunk["chunk_id"])
        assert h is not None
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[])


async def test_hierarchy_exception_branch(pool, clean_doc):
    source, doc_id = clean_doc

    class Bad:
        def to_dict(self):
            raise RuntimeError("boom")

    await upsert_document(pool, source=source, doc_id=doc_id, content_hash="sha256:x")
    chunk = {
        "chunk_id": f"{doc_id}-b",
        "source": source,
        "doc_id": doc_id,
        "doc_type": "proposicao",
        "doc_meta": {},
        "breadcrumb": "b",
        "hierarchy": Bad(),
        "kind": "dispositivo",
        "chunk_text": "hi",
        "text": "hi",
        "ordinal": 1,
        "char_span": None,
        "page": None,
        "extraction_quality": "high",
        "content_hash": "sha256:ch2",
    }
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[chunk])
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[])


async def test_upsert_document_updated_path(pool, clean_doc):
    source, doc_id = clean_doc
    text = "Art. 1º A."
    meta = {"doc_id": doc_id, "source": source}
    chunks = chunk_document(text, meta)
    r1 = await upsert(pool, source=source, doc_id=doc_id, chunks=chunks, content_hash="sha256:aaa")
    assert r1.new == 1
    r2 = await upsert(pool, source=source, doc_id=doc_id, chunks=chunks, content_hash="sha256:bbb")
    assert r2.updated == 1


async def test_upsert_chunks_embedding_preserve_and_else_branch(pool, clean_doc):
    source, doc_id = clean_doc
    await upsert_document(pool, source=source, doc_id=doc_id, content_hash="sha256:x")

    class ListHierarchy(list):
        pass

    chunk = {
        "chunk_id": f"{doc_id}-e",
        "source": source,
        "doc_id": doc_id,
        "doc_type": "proposicao",
        "doc_meta": {},
        "breadcrumb": "b",
        "hierarchy": ListHierarchy([1, 2]),
        "kind": "dispositivo",
        "chunk_text": "hi",
        "text": "hi",
        "ordinal": 1,
        "char_span": None,
        "page": None,
        "extraction_quality": "high",
        "content_hash": "sha256:ch",
    }
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[chunk])
    # second call: same hash, no embedding -> preserve branch
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[chunk])
    await upsert_chunks(pool, source=source, doc_id=doc_id, chunks=[])
