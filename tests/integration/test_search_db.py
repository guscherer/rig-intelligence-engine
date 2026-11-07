"""Testes de integração da busca (exigem Postgres)."""

from __future__ import annotations

import os

import asyncpg
import pytest

from rig.retrieval.search import SearchFilters, dense_search, sparse_search

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


async def test_filter_reduces_candidates_dense(pool) -> None:
    vec = [0.0] * 1024
    all_res = await dense_search(pool, "x", query_vector=vec, limit=100)
    filt_res = await dense_search(
        pool, "x", query_vector=vec, filters=SearchFilters(kind="dispositivo"), limit=100
    )
    assert len(filt_res) <= len(all_res)
    assert all(r.text is not None for r in filt_res)


async def test_filter_reduces_candidates_sparse(pool) -> None:
    all_res = await sparse_search(pool, "artigo", limit=100)
    filt_res = await sparse_search(
        pool, "artigo", filters=SearchFilters(kind="dispositivo"), limit=100
    )
    assert len(filt_res) <= len(all_res)


async def test_output_has_required_fields(pool) -> None:
    vec = [0.0] * 1024
    res = await dense_search(pool, "x", query_vector=vec, limit=5)
    if res:
        r = res[0]
        assert r.breadcrumb
        assert r.doc_id
        assert isinstance(r.score, float)
