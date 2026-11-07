"""Testes do golden set de retrieval (F1.4)."""

from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest
import yaml

GOLDEN_PATH = Path("eval/golden/retrieval_v1.yaml")
REQUIRED_FIELDS = {"query", "chunk_ouro", "doc_id", "justificativa"}


def _load() -> dict:
    with GOLDEN_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_golden_retrieval_structure() -> None:
    data = _load()
    assert data["label_status"] == "provisional"
    assert data["provisional"] is True
    assert data["n"] == 40
    items = data["items"]
    assert len(items) == 40
    for item in items:
        assert REQUIRED_FIELDS.issubset(item.keys())
        assert isinstance(item["query"], str) and item["query"].strip()
        assert isinstance(item["chunk_ouro"], str) and item["chunk_ouro"].strip()
        assert isinstance(item["doc_id"], (str, int))
        assert isinstance(item["justificativa"], str) and item["justificativa"].strip()
    # anotacao de perfil de retrieval (denso vs esparso)
    profiles = {i["retrieval_profile"] for i in items}
    assert "dense_only" in profiles
    assert "sparse_only" in profiles
    # distribuicao registrada
    assert "distribution" in data
    assert data["distribution"]["by_doc_type"]
    assert data["distribution"]["by_retrieval_profile"]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://rig:rig@localhost:5432/rig")
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


@pytest.mark.integration
async def test_golden_retrieval_chunks_exist_in_db() -> None:
    pool = None
    try:
        pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)
    except Exception as exc:
        pytest.skip(f"Postgres indisponivel: {exc}")
    assert pool is not None
    data = _load()
    missing: list[str] = []
    mismatches: list[str] = []
    async with pool.acquire() as conn:
        for item in data["items"]:
            cid = item["chunk_ouro"]
            row = await conn.fetchrow(
                "SELECT doc_id, chunk_text FROM chunks WHERE chunk_id = $1", cid
            )
            if row is None:
                missing.append(cid)
                continue
            if str(row["doc_id"]) != str(item["doc_id"]):
                mismatches.append(f"{cid}: db={row['doc_id']} yaml={item['doc_id']}")
            if not (row["chunk_text"] or "").strip():
                missing.append(f"{cid}: empty text")
    await pool.close()
    assert not missing, f"chunk_id inexistentes/vazios: {missing}"
    assert not mismatches, f"doc_id divergentes: {mismatches}"
