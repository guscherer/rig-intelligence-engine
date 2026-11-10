"""Testes de regressão de ``rig.retrieval.fetch`` (jsonb como ``str``, não ``dict``).

O asyncpg devolve a coluna ``jsonb`` como ``str``; ``fetch_document`` e
``_row_to_search_result`` precisam decodificá-la (``json.loads``) — o bug de
produção F2 descartava a ementa inteira quando ``doc_meta`` vinha como string.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from rig.retrieval.fetch import _row_to_search_result, fetch_document


class _FakeRow(dict):
    """Dict que emula a row do asyncpg (acesso por chave)."""


class _FakeConn:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def fetchrow(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        return self._row


class _FakePool:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def acquire(self) -> _FakeConn:
        return _FakeConn(self._row)


META_DICT = {"ano": 2023, "doc_id": "2487262", "ementa": "Dispõe sobre a IA."}
META_STR = json.dumps(META_DICT, ensure_ascii=False)


def _chunk_row(doc_meta: Any) -> dict[str, Any]:
    return {
        "chunk_id": "c1",
        "doc_id": "2487262",
        "breadcrumb": "Art. 1º",
        "page": 1,
        "chunk_text": "texto",
        "source": "camara",
        "doc_meta": doc_meta,
    }


# ── fetch_document ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_document_decodes_jsonb_string() -> None:
    """doc_meta em ``str`` (jsonb do asyncpg) vira dict com ementa preenchida."""
    pool = _FakePool({"doc_meta": META_STR})
    result = await fetch_document(pool, "2487262")  # type: ignore[arg-type]
    assert isinstance(result, dict)
    assert result["ementa"] == "Dispõe sobre a IA."
    assert result["doc_id"] == "2487262"


@pytest.mark.asyncio
async def test_fetch_document_accepts_dict_unchanged() -> None:
    pool = _FakePool({"doc_meta": META_DICT})
    result = await fetch_document(pool, "2487262")  # type: ignore[arg-type]
    assert result == META_DICT


@pytest.mark.asyncio
async def test_fetch_document_none_meta_returns_empty_dict() -> None:
    pool = _FakePool({"doc_meta": None})
    result = await fetch_document(pool, "2487262")  # type: ignore[arg-type]
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_document_missing_row_returns_none() -> None:
    pool = _FakePool(None)
    result = await fetch_document(pool, "2487262")  # type: ignore[arg-type]
    assert result is None


@pytest.mark.asyncio
async def test_fetch_document_invalid_json_string_returns_empty_dict() -> None:
    pool = _FakePool({"doc_meta": "não é json {{{"})
    result = await fetch_document(pool, "2487262")  # type: ignore[arg-type]
    assert result == {}


# ── _row_to_search_result ────────────────────────────────────────────────────


def test_row_to_search_result_decodes_jsonb_string() -> None:
    row = _chunk_row(META_STR)
    result = _row_to_search_result(row)
    assert result.doc_meta == META_DICT


def test_row_to_search_result_accepts_dict_unchanged() -> None:
    row = _chunk_row(META_DICT)
    result = _row_to_search_result(row)
    assert result.doc_meta == META_DICT


def test_row_to_search_result_none_meta_returns_empty_dict() -> None:
    row = _chunk_row(None)
    result = _row_to_search_result(row)
    assert result.doc_meta == {}
