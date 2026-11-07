"""Testes do pipeline de ingestao (gate usa MockTransport)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import asyncpg
import httpx
import pytest

from rig.ingestion import CamaraClient, run_ingest

pytestmark = pytest.mark.integration

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "proposicoes"
PIDS = ["2646598", "2644408"]


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
    except Exception as exc:  # pragma: no cover - ambiente sem Postgres
        pytest.skip(f"Postgres indisponivel: {exc}")
    try:
        yield p
    finally:
        await p.close()


def _make_transport() -> httpx.MockTransport:
    fixtures = {pid: (FIXTURE_DIR / f"{pid}.pdf").read_bytes() for pid in PIDS}
    meta = {}
    for pid in PIDS:
        meta[pid] = json.loads((FIXTURE_DIR / f"{pid}.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://example.com/teor/"):
            pid = url.rsplit("/", maxsplit=1)[-1].replace(".pdf", "")
            if pid in fixtures:
                return httpx.Response(200, content=fixtures[pid])
        path = request.url.path
        if path.endswith("/proposicoes"):
            pagina = request.url.params.get("pagina", "1")
            if pagina != "1":
                return httpx.Response(200, json={"dados": []})
            data = [{"id": int(pid)} for pid in PIDS]
            return httpx.Response(200, json={"dados": data})
        if "/proposicoes/" in path and not path.endswith("/proposicoes"):
            pid = path.split("/")[-1]
            return httpx.Response(
                200,
                json={
                    "dados": {
                        "id": int(pid),
                        "siglaTipo": "PL",
                        "numero": 1,
                        "ano": 2024,
                        "ementa": "ementa de teste",
                        "keywords": "kw",
                        "urlInteiroTeor": f"https://example.com/teor/{pid}.pdf",
                        "dataApresentacao": "2024-01-01",
                        "statusProposicao": {"descricaoSituacao": "Em tramitacao"},
                    }
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ingest_pipeline_mock(pool, tmp_path):
    for pid in PIDS:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM chunks WHERE source='camara' AND doc_id=$1", pid)
            await conn.execute("DELETE FROM documents WHERE source='camara' AND doc_id=$1", pid)
            await conn.execute(
                "DELETE FROM ingest_cursor WHERE source='camara' AND scope=$1", "PL:2024"
            )

    cache_dir = tmp_path / "cache"
    data_dir = tmp_path / "data"
    transport = _make_transport()
    client = CamaraClient(transport=transport, cache_dir=cache_dir, rps=1000.0)
    summary = await run_ingest(
        client=client,
        pool=pool,
        anos=[2024],
        tipos=["PL"],
        data_dir=str(data_dir),
        manifest_path=str(data_dir / "manifest.json"),
        rps=1000.0,
    )
    await client.aclose()

    assert summary["documents"] >= 1
    assert summary["chunks"] >= 1

    # contagens antes da segunda execucao
    async with pool.acquire() as conn:
        nd_before = await conn.fetchval("SELECT count(*) FROM documents WHERE source='camara'")
        nc_before = await conn.fetchval("SELECT count(*) FROM chunks WHERE source='camara'")

    transport2 = _make_transport()
    client2 = CamaraClient(transport=transport2, cache_dir=tmp_path / "cache2", rps=1000.0)
    await run_ingest(
        client=client2,
        pool=pool,
        anos=[2024],
        tipos=["PL"],
        data_dir=str(data_dir),
        manifest_path=str(data_dir / "manifest.json"),
        rps=1000.0,
    )
    await client2.aclose()
    async with pool.acquire() as conn:
        nd_after = await conn.fetchval("SELECT count(*) FROM documents WHERE source='camara'")
        nc_after = await conn.fetchval("SELECT count(*) FROM chunks WHERE source='camara'")
    assert nd_after == nd_before
    assert nc_after == nc_before


@pytest.mark.live
@pytest.mark.asyncio
async def test_ingest_live_small(tmp_path):
    summary = await run_ingest(
        anos=[2025],
        tipos=["PL"],
        data_dir=str(tmp_path / "data"),
        manifest_path=str(tmp_path / "manifest_live.json"),
    )
    assert summary["documents"] >= 0
