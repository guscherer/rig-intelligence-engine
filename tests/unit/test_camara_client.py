"""Testes unitarios do CamaraClient (sem rede)."""

from __future__ import annotations

import httpx
import pytest

from rig.ingestion import CamaraClient


def _json_response(status: int, data: list[dict], headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json={"dados": data}, headers=headers or {})


@pytest.mark.asyncio
async def test_pagination(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        pagina = int(request.url.params["pagina"])
        if pagina == 1:
            data = [{"id": 200 - i} for i in range(100)]
        elif pagina == 2:
            data = [{"id": 100 - i} for i in range(50)]
        else:
            data = []
        return _json_response(200, data)

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0
    ) as client:
        results = [p async for p in client.listar_proposicoes("PL", 2025)]

    assert len(results) == 150
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_desde_id_stops(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        pagina = int(request.url.params["pagina"])
        data = [{"id": 200 - i} for i in range(100)] if pagina == 1 else []
        return _json_response(200, data)

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0
    ) as client:
        results = [p async for p in client.listar_proposicoes("PL", 2025, desde_id=150)]

    assert calls["n"] == 1
    assert len(results) == 50
    assert all(p["id"] > 150 for p in results)


@pytest.mark.asyncio
async def test_empty_page(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _json_response(200, [])

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0
    ) as client:
        results = [p async for p in client.listar_proposicoes("PL", 2025)]

    assert results == []
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_retry_500(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(500)
        if calls["n"] == 3:
            return _json_response(200, [{"id": 1}])
        return _json_response(200, [])

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0, max_retries=3
    ) as client:
        results = [p async for p in client.listar_proposicoes("PL", 2025)]

    assert results == [{"id": 1}]
    assert calls["n"] == 4


@pytest.mark.asyncio
async def test_retry_429_retry_after(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if calls["n"] == 2:
            return _json_response(200, [{"id": 2}])
        return _json_response(200, [])

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0, max_retries=3
    ) as client:
        results = [p async for p in client.listar_proposicoes("PL", 2025)]

    assert results == [{"id": 2}]
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_404_propagates(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in client.listar_proposicoes("PL", 2025):
                pass


@pytest.mark.asyncio
async def test_cache_hit_no_call(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _json_response(200, [{"id": 7}])
        return _json_response(200, [])

    cache_dir = tmp_path / "cache"
    transport = httpx.MockTransport(handler)
    async with CamaraClient(transport=transport, cache_dir=cache_dir, rps=1000.0) as client:
        first = [p async for p in client.listar_proposicoes("PL", 2025)]
    assert first == [{"id": 7}]
    assert calls["n"] == 2

    def handler2(request: httpx.Request) -> httpx.Response:
        raise AssertionError("rede chamada em cache hit")

    transport2 = httpx.MockTransport(handler2)
    async with CamaraClient(transport=transport2, cache_dir=cache_dir, rps=1000.0) as client:
        second = [p async for p in client.listar_proposicoes("PL", 2025)]
    assert second == [{"id": 7}]


@pytest.mark.asyncio
async def test_detalhar(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "dados": {
                    "id": 2487262,
                    "siglaTipo": "PL",
                    "numero": 2338,
                    "ano": 2023,
                    "ementa": "Marco legal da IA",
                    "keywords": "inteligencia artificial",
                    "urlInteiroTeor": "https://example.com/pdf",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0
    ) as client:
        prop = await client.detalhar(2487262)

    assert prop.id == 2487262
    assert prop.sigla_tipo == "PL"
    assert prop.url_inteiro_teor == "https://example.com/pdf"
    assert prop["siglaTipo"] == "PL"


@pytest.mark.asyncio
async def test_inteiro_teor(tmp_path) -> None:
    payload = b"%PDF-1.4 fake"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "application/pdf"})

    transport = httpx.MockTransport(handler)
    async with CamaraClient(
        transport=transport, cache_dir=tmp_path / "cache", rps=1000.0
    ) as client:
        data = await client.inteiro_teor("https://example.com/teor.pdf")

    assert data == payload
