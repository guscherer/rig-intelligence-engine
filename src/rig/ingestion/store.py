"""Gravação idempotente do corpus em Postgres (asyncpg)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# asyncpg tipado via Any nos parâmetros de pool


@dataclass
class IngestCounters:
    """Contadores reais de uma execução de ingestão."""

    fetched: int = 0
    new: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except Exception:
        return {}


def _chunk_text(chunk: Any) -> str:
    if hasattr(chunk, "text"):
        return str(chunk.text)
    if isinstance(chunk, dict):
        return str(chunk.get("text", chunk.get("chunk_text", "")))
    return str(chunk)


def _chunk_id(chunk: Any) -> str:
    if hasattr(chunk, "chunk_id"):
        return str(chunk.chunk_id)
    if isinstance(chunk, dict):
        return str(chunk.get("chunk_id", ""))
    return ""


def _chunk_hash(chunk: Any) -> str:
    if hasattr(chunk, "content_hash"):
        return str(chunk.content_hash)
    if isinstance(chunk, dict):
        return str(chunk.get("content_hash", ""))
    return "sha256:" + hashlib.sha256(_chunk_text(chunk).encode()).hexdigest()


def _chunk_field(chunk: Any, name: str, default: Any = None) -> Any:
    if hasattr(chunk, name):
        return getattr(chunk, name)
    if isinstance(chunk, dict):
        return chunk.get(name, default)
    return default


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _doc_content_hash(chunks: list[Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    # Prefer hashes dos chunks quando disponíveis.
    hashes = [_chunk_hash(c) for c in chunks]
    joined = "|".join(hashes) if all(hashes) else "\n".join(_chunk_text(c) for c in chunks)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


async def upsert_document(
    pool: Any,
    *,
    source: str,
    doc_id: str,
    doc_type: str = "proposicao",
    doc_meta: dict[str, Any] | None = None,
    content_hash: str | None = None,
) -> str:
    """Insere ou atualiza o documento. Retorna 'new', 'updated' ou 'skipped'."""
    meta = _as_dict(doc_meta)
    h = content_hash or ""
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT content_hash FROM documents WHERE source=$1 AND doc_id=$2",
            source,
            doc_id,
        )
        if existing is None:
            await conn.execute(
                """
                INSERT INTO documents (source, doc_id, doc_type, doc_meta, content_hash)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                """,
                source,
                doc_id,
                doc_type,
                _json(meta),
                h,
            )
            return "new"
        if existing["content_hash"] == h and h != "":
            return "skipped"
        await conn.execute(
            """
            UPDATE documents
               SET doc_type=$3, doc_meta=$4::jsonb, content_hash=$5, updated_at=now()
             WHERE source=$1 AND doc_id=$2
            """,
            source,
            doc_id,
            doc_type,
            _json(meta),
            h,
        )
        return "updated"


async def upsert_chunks(
    pool: Any,
    *,
    source: str,
    doc_id: str,
    chunks: list[Any],
    embedding_by_chunk: dict[str, list[float]] | None = None,
) -> None:
    """Upsert de chunks, preservando embedding quando content_hash não mudou."""
    emb_map = embedding_by_chunk or {}
    incoming_ids = [_chunk_id(c) for c in chunks]
    async with pool.acquire() as conn, conn.transaction():
        for chunk in chunks:
            cid = _chunk_id(chunk)
            text = _chunk_text(chunk)
            chash = _chunk_hash(chunk)
            meta = _as_dict(_chunk_field(chunk, "doc_meta", {}))
            hierarchy = _chunk_field(chunk, "hierarchy", None)
            if hierarchy is not None and not isinstance(hierarchy, (dict, str)):
                try:
                    if hasattr(hierarchy, "to_dict"):
                        hierarchy = hierarchy.to_dict()
                    else:
                        hierarchy = _as_dict(hierarchy)
                except Exception:
                    hierarchy = _as_dict(hierarchy)
            breadcrumb = str(_chunk_field(chunk, "breadcrumb", ""))
            kind = str(_chunk_field(chunk, "kind", "dispositivo"))
            ordinal = int(_chunk_field(chunk, "ordinal", 0) or 0)
            char_span = _chunk_field(chunk, "char_span", None)
            page = _chunk_field(chunk, "page", None)
            quality = _chunk_field(chunk, "extraction_quality", "high")
            doc_type = str(_chunk_field(chunk, "doc_type", "proposicao"))
            embedding = emb_map.get(cid)
            # Preserva embedding existente se hash não mudou.
            existing = await conn.fetchrow(
                "SELECT content_hash, embedding FROM chunks WHERE chunk_id=$1",
                cid,
            )
            if existing is not None and existing["content_hash"] == chash and embedding is None:
                embedding = existing["embedding"]
            await conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, source, doc_id, doc_type, doc_meta, breadcrumb,
                    hierarchy, kind, chunk_text, ordinal, char_span, page,
                    extraction_quality, content_hash, embedding
                ) VALUES (
                    $1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, $9, $10,
                    $11, $12, $13, $14, $15
                )
                ON CONFLICT (chunk_id) DO UPDATE SET
                    source = EXCLUDED.source,
                    doc_id = EXCLUDED.doc_id,
                    doc_type = EXCLUDED.doc_type,
                    doc_meta = EXCLUDED.doc_meta,
                    breadcrumb = EXCLUDED.breadcrumb,
                    hierarchy = EXCLUDED.hierarchy,
                    kind = EXCLUDED.kind,
                    chunk_text = EXCLUDED.chunk_text,
                    ordinal = EXCLUDED.ordinal,
                    char_span = EXCLUDED.char_span,
                    page = EXCLUDED.page,
                    extraction_quality = EXCLUDED.extraction_quality,
                    content_hash = EXCLUDED.content_hash,
                    embedding = EXCLUDED.embedding,
                    updated_at = now()
                """,
                cid,
                source,
                doc_id,
                doc_type,
                _json(meta),
                breadcrumb,
                _json(hierarchy if hierarchy is not None else {}),
                kind,
                text,
                ordinal,
                char_span,
                page,
                quality,
                chash,
                embedding,
            )
        # Remove chunks que não estão mais presentes.
        if incoming_ids:
            await conn.execute(
                "DELETE FROM chunks WHERE source=$1 AND doc_id=$2 "
                "AND NOT (chunk_id = ANY($3::text[]))",
                source,
                doc_id,
                incoming_ids,
            )
        else:
            await conn.execute(
                "DELETE FROM chunks WHERE source=$1 AND doc_id=$2",
                source,
                doc_id,
            )


async def upsert(
    pool: Any,
    *,
    source: str,
    doc_id: str,
    chunks: list[Any],
    doc_type: str = "proposicao",
    doc_meta: dict[str, Any] | None = None,
    content_hash: str | None = None,
    embedding_by_chunk: dict[str, list[float]] | None = None,
) -> IngestCounters:
    """Upsert completo de um documento + chunks. Retorna contadores."""
    counters = IngestCounters(fetched=1)
    h = _doc_content_hash(chunks, content_hash)
    meta = (
        doc_meta
        if doc_meta is not None
        else (_chunk_field(chunks[0], "doc_meta", {}) if chunks else {})
    )
    status = await upsert_document(
        pool,
        source=source,
        doc_id=doc_id,
        doc_type=doc_type,
        doc_meta=meta,
        content_hash=h,
    )
    if status == "new":
        counters.new = 1
    elif status == "updated":
        counters.updated = 1
    else:
        counters.skipped = 1
    if status != "skipped":
        await upsert_chunks(
            pool,
            source=source,
            doc_id=doc_id,
            chunks=chunks,
            embedding_by_chunk=embedding_by_chunk,
        )
    return counters


async def record_ingest_run(
    pool: Any,
    *,
    source: str | None = None,
    scope: str | None = None,
    counters: IngestCounters | None = None,
    status: str = "completed",
    error: str | None = None,
    dataset_version: str | None = None,
) -> int:
    """Grava uma linha em ingest_run e retorna o id."""
    c = counters or IngestCounters()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ingest_run (
                source, scope, fetched, new, updated, skipped, failed,
                dataset_version, status, error, finished_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
            RETURNING id
            """,
            source,
            scope,
            c.fetched,
            c.new,
            c.updated,
            c.skipped,
            c.failed,
            dataset_version,
            status,
            error,
        )
        return int(row["id"])


# Aliases para nomes alternativos esperados por consumidores.
upsert_document_and_chunks = upsert
record_run = record_ingest_run
ingest_run_record = record_ingest_run


async def get_cursor(pool: Any, source: str, scope: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_id, last_ts, updated_at FROM ingest_cursor WHERE source=$1 AND scope=$2",
            source,
            scope,
        )
        if row is None:
            return None
        return {
            "last_id": row["last_id"],
            "last_ts": row["last_ts"],
            "updated_at": row["updated_at"],
        }


async def update_cursor(
    pool: Any,
    source: str,
    scope: str,
    *,
    last_id: str | None = None,
    last_ts: Any = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ingest_cursor (source, scope, last_id, last_ts, updated_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (source, scope) DO UPDATE SET
                last_id = EXCLUDED.last_id,
                last_ts = EXCLUDED.last_ts,
                updated_at = now()
            """,
            source,
            scope,
            last_id,
            last_ts,
        )
