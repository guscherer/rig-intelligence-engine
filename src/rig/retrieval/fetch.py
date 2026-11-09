"""Leitura direta de documento/chunks por ``doc_id`` (plano online, sem embedding).

O nó ``retrieve`` semântico (``search``) serve consulta livre; para um run sobre
**um** documento específico (``make run --id 2487262``) a recuperação correta é
buscar os chunks do próprio documento em ordem de leitura (``ordinal``). Isso
não depende da stack de embedding nem do FTS.
"""

from __future__ import annotations

from typing import Any

from rig.retrieval.search import SearchResult

SOURCE = "camara"


def _row_to_search_result(row: Any) -> SearchResult:
    return SearchResult(
        chunk_id=str(row["chunk_id"]),
        doc_id=str(row["doc_id"]),
        breadcrumb=str(row["breadcrumb"]),
        page=(int(row["page"]) if row["page"] is not None else None),
        score=0.0,
        text=str(row["chunk_text"]),
        source=str(row.get("source") or SOURCE),
        doc_meta=(dict(row["doc_meta"]) if isinstance(row["doc_meta"], dict) else {}),
    )


async def fetch_document(
    pool: Any,
    doc_id: str,
    *,
    source: str = SOURCE,
) -> dict[str, Any] | None:
    """Devolve o ``doc_meta`` (ementa, keywords, sigla_tipo, ...) do documento.

    Retorna ``None`` quando o documento não existe (o chamador decide o erro).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT doc_meta FROM documents WHERE source=$1 AND doc_id=$2",
            source,
            doc_id,
        )
    if row is None:
        return None
    meta = row["doc_meta"]
    return dict(meta) if isinstance(meta, dict) else {}


async def fetch_doc_chunks(
    pool: Any,
    doc_id: str,
    *,
    source: str = SOURCE,
    limit: int = 16,
) -> list[SearchResult]:
    """Devolve os chunks do documento em ordem de leitura (``ordinal``)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chunk_id, source, doc_id, breadcrumb, page, chunk_text, doc_meta "
            "FROM chunks WHERE source=$1 AND doc_id=$2 ORDER BY ordinal "
            "LIMIT $3",
            source,
            doc_id,
            int(limit),
        )
    return [_row_to_search_result(r) for r in rows]


__all__ = ["fetch_doc_chunks", "fetch_document"]
