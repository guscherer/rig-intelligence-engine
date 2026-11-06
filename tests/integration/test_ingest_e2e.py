"""Testes ponta a ponta de ingestão."""

from __future__ import annotations

import json
import os
from pathlib import Path

import asyncpg
import pytest

from rig.ingestion.chunker import chunk_document
from rig.ingestion.pdf import extract_pdf
from rig.ingestion.store import upsert

pytestmark = pytest.mark.integration

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "proposicoes"
PIDS = ["2646598", "2644408"]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://rig:rig@localhost:5432/rig")
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


def _load_fixture(pid: str) -> tuple[bytes, dict]:
    pdf = (FIXTURE_DIR / f"{pid}.pdf").read_bytes()
    meta = json.loads((FIXTURE_DIR / f"{pid}.json").read_text(encoding="utf-8"))
    return pdf, meta


def _doc_meta(fixture: dict) -> dict:
    return {
        "doc_id": fixture["doc_id"],
        "source": fixture["source"],
        "doc_type": fixture["doc_type"],
        "extraction_quality": fixture["extraction_quality"],
    }


async def _clean(pool: asyncpg.Pool, source: str, doc_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chunks WHERE source=$1 AND doc_id=$2", source, doc_id)
        await conn.execute("DELETE FROM documents WHERE source=$1 AND doc_id=$2", source, doc_id)


@pytest.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)
    except Exception as exc:  # pragma: no cover - ambiente sem Postgres
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        yield p
    finally:
        await p.close()


@pytest.mark.parametrize("pid", PIDS)
async def test_e2e_fixture_to_store(pool, pid):
    source = "camara"
    await _clean(pool, source, pid)
    pdf, fixture = _load_fixture(pid)
    extracted = extract_pdf(pdf)
    meta = _doc_meta(fixture)
    chunks = chunk_document(extracted.text, meta)

    assert [c.chunk_id for c in chunks] == fixture["expected_chunk_ids"]

    counters = await upsert(pool, source=source, doc_id=pid, chunks=chunks, doc_meta=meta)
    assert counters.fetched == 1
    assert counters.new == 1

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chunk_id FROM chunks WHERE source=$1 AND doc_id=$2 ORDER BY ordinal",
            source,
            pid,
        )
    selected = [row["chunk_id"] for row in rows]
    assert selected == [chunk.chunk_id for chunk in chunks]

    await _clean(pool, source, pid)


@pytest.mark.parametrize("pid", PIDS)
async def test_e2e_idempotency(pool, pid):
    source = "camara"
    await _clean(pool, source, pid)
    pdf, fixture = _load_fixture(pid)
    extracted = extract_pdf(pdf)
    meta = _doc_meta(fixture)
    chunks = chunk_document(extracted.text, meta)

    first = await upsert(pool, source=source, doc_id=pid, chunks=chunks, doc_meta=meta)
    assert first.new == 1
    assert first.skipped == 0

    second = await upsert(pool, source=source, doc_id=pid, chunks=chunks, doc_meta=meta)
    assert second.skipped == 1
    assert second.new == 0
    assert second.updated == 0

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT count(*) FROM chunks WHERE source=$1 AND doc_id=$2", source, pid
        )
        assert total == len(chunks)
        duplicates = await conn.fetchval(
            "SELECT count(*) - count(DISTINCT chunk_id) FROM chunks WHERE source=$1 AND doc_id=$2",
            source,
            pid,
        )
        assert duplicates == 0

    await _clean(pool, source, pid)


def test_chunker_snapshot_real_proposition():
    pid = PIDS[0]
    pdf, fixture = _load_fixture(pid)
    extracted = extract_pdf(pdf)
    meta = _doc_meta(fixture)
    chunks = chunk_document(extracted.text, meta)
    assert [chunk.chunk_id for chunk in chunks] == fixture["expected_chunk_ids"]
