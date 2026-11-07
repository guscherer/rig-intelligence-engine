"""Backfill idempotente de embeddings (bge-m3) em ``chunks.embedding``.

O modelo roda localmente via ``sentence-transformers``. O import do stack pesado
(torch / sentence-transformers) e feito de forma lazy para que ``make check``
continue verde mesmo sem o extra ``embed`` instalado.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from rig.core.db import close_pool, get_pool

__all__ = [
    "BackfillStats",
    "Encoder",
    "backfill",
    "backfill_embeddings",
    "embed_chunks",
    "embedding_dim",
    "encode_texts",
    "load_encoder",
    "main",
    "model_name",
    "run_backfill",
    "validate_dimension",
]


def embedding_dim() -> int:
    """Dimensao esperada, lida de ``EMBEDDING_DIM`` (default 1024)."""
    raw = os.environ.get("EMBEDDING_DIM", "1024")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"EMBEDDING_DIM invalido: {raw!r}") from exc


def model_name() -> str:
    """Nome do modelo, lido de ``MODEL_EMBEDDING``."""
    return os.environ.get("MODEL_EMBEDDING", "BAAI/bge-m3")


class Encoder:
    """Protocolo minimo de um encoder de texto.

    Qualquer objeto com metodo ``encode(texts)`` (ou chamavel) serve, o que
    permite injetar encoders falsos nos testes.
    """


def _to_list(vector: Any) -> list[float]:
    """Converte numpy array / tupla / lista em ``list[float]``."""
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(x) for x in vector]


def validate_dimension(vector: Any, expected: int | None = None) -> None:
    """Valida a dimensao de um vetor contra ``EMBEDDING_DIM``.

    Levanta ``ValueError`` com mensagem clara se divergir.
    """
    if expected is None:
        expected = embedding_dim()
    size = len(vector) if hasattr(vector, "__len__") else None
    if size is None or size != expected:
        raise ValueError(
            f"dimensao do embedding divergente: obtido {size}, esperado {expected} "
            f"(EMBEDDING_DIM). Modelo possivelmente incompativel."
        )


def _call_encoder(encoder: Any, texts: list[str], batch_size: int) -> list[list[float]]:
    """Chama o encoder de forma tolerante a diferentes assinaturas."""
    if hasattr(encoder, "encode"):
        try:
            result = encoder.encode(texts, batch_size=batch_size)
        except TypeError:
            result = encoder.encode(texts)
    elif callable(encoder):
        try:
            result = encoder(texts, batch_size=batch_size)
        except TypeError:
            result = encoder(texts)
    else:
        raise TypeError("encoder deve expor encode() ou ser chamavel")
    return [_to_list(v) for v in result]


def encode_texts(
    encoder: Any,
    texts: Iterable[str],
    *,
    batch_size: int = 32,
) -> list[list[float]]:
    """Codifica uma lista de textos, validando a dimensao de cada vetor."""
    items = list(texts)
    if not items:
        return []
    vectors = _call_encoder(encoder, items, batch_size)
    if len(vectors) != len(items):
        raise ValueError(f"encoder retornou {len(vectors)} vetores para {len(items)} textos")
    expected = embedding_dim()
    for v in vectors:
        validate_dimension(v, expected)
    return vectors


def load_encoder(model: str | None = None) -> Any:
    """Carrega o encoder real (lazy import de sentence-transformers)."""
    name = model or model_name()
    try:
        module = importlib.import_module("sentence_transformers")  # lazy: gate verde sem embed
        sentence_transformer_cls = module.SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "stack de embedding nao instalada; rode `uv sync --extra embed`"
        ) from exc
    return sentence_transformer_cls(name)


@dataclass
class BackfillStats:
    """Resultado de uma execucao de backfill."""

    total: int = 0
    embedded: int = 0
    skipped: int = 0
    failed: int = 0
    duration_s: float = 0.0
    throughput: float = 0.0
    model: str = ""
    dim: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return self.duration_s

    @property
    def elapsed_s(self) -> float:
        return self.duration_s

    @property
    def chunks_per_second(self) -> float:
        return self.throughput

    @property
    def rate(self) -> float:
        return self.throughput

    @property
    def processed(self) -> int:
        return self.embedded


async def _fetch_pending(pool: Any, limit: int | None) -> list[tuple[str, str]]:
    """Busca chunk_id/texto com embedding NULL."""
    sql = "SELECT chunk_id, chunk_text FROM chunks WHERE embedding IS NULL"
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT $1"
        params.append(int(limit))
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [(str(r["chunk_id"]), str(r["chunk_text"])) for r in rows]


async def _write_embeddings(pool: Any, pairs: list[tuple[str, list[float]]]) -> None:
    """Grava os vetores em lote."""
    if not pairs:
        return
    async with pool.acquire() as conn, conn.transaction():
        for chunk_id, vector in pairs:
            vector_str = "[" + ",".join(repr(float(x)) for x in vector) + "]"
            await conn.execute(
                "UPDATE chunks SET embedding = $1::vector, updated_at = now() WHERE chunk_id = $2",
                vector_str,
                chunk_id,
            )


async def _resolve_pending(
    pool: Any,
    rows: list[tuple[str, str]] | None,
    fetch: Any,
    limit: int | None,
) -> list[tuple[str, str]]:
    if rows is not None:
        return list(rows)
    if pool is None:
        return []
    if fetch is not None:
        try:
            result = fetch(pool, limit)
        except TypeError:
            result = fetch(pool)
    else:
        result = _fetch_pending(pool, limit)
    cast_result: Any = result
    if asyncio.iscoroutine(cast_result):
        cast_result = await cast_result
    return list(cast_result)


async def _write_pairs(pool: Any, pairs: list[tuple[str, list[float]]], write: Any) -> None:
    """Grava um conjunto de (id, vetor), delegando ao writer injetado."""
    if write is not None:
        result = write(pool, pairs)
        if asyncio.iscoroutine(result):
            await result
    elif pool is not None:
        await _write_embeddings(pool, pairs)


async def _process_one(
    stats: BackfillStats,
    encoder: Any,
    chunk_id: str,
    text: str,
    pool: Any,
    write: Any,
    batch_size: int,
) -> None:
    """Processa um unico chunk, isolando falhas para nao contaminar vizinhos."""
    try:
        vectors = encode_texts(encoder, [text], batch_size=batch_size)
    except Exception as exc:
        stats.failed += 1
        stats.errors.append(f"{type(exc).__name__}: {exc} (chunk_id={chunk_id})")
        return
    try:
        await _write_pairs(pool, [(chunk_id, vectors[0])], write)
    except Exception as exc:
        stats.failed += 1
        stats.errors.append(f"{type(exc).__name__}: {exc} (chunk_id={chunk_id})")
        return
    stats.embedded += 1


async def _process_batch(
    stats: BackfillStats,
    encoder: Any,
    batch: list[tuple[str, str]],
    pool: Any,
    write: Any,
    batch_size: int,
) -> None:
    """Processa um lote; em falha, isola chunk a chunk (sem derrubar vizinhos)."""
    ids = [b[0] for b in batch]
    texts = [b[1] for b in batch]
    try:
        vectors = encode_texts(encoder, texts, batch_size=batch_size)
        pairs = list(zip(ids, vectors, strict=True))
        await _write_pairs(pool, pairs, write)
        stats.embedded += len(batch)
        return
    except Exception as exc:
        stats.errors.append(f"batch failed: {type(exc).__name__}: {exc}; isolating per chunk")
    for chunk_id, text in batch:
        await _process_one(stats, encoder, chunk_id, text, pool, write, batch_size)


async def backfill_embeddings(  # noqa: PLR0913 - backfill aceita overrides opcionais (pool, encoder, batch, limit, rows, fetch, write) para testabilidade
    pool: Any = None,
    *,
    encoder: Any = None,
    batch_size: int = 32,
    model: str | None = None,
    dim: int | None = None,
    limit: int | None = None,
    rows: list[tuple[str, str]] | None = None,
    fetch: Any = None,
    write: Any = None,
) -> BackfillStats:
    """Backfill idempotente de ``chunks.embedding``.

    Processa apenas linhas com ``embedding IS NULL``. Retorna estatisticas com
    throughput medido. ``encoder`` pode ser injetado (testes); caso contrario
    carrega o modelo real (lazy).
    """
    if dim is not None:
        os.environ["EMBEDDING_DIM"] = str(dim)
    expected_dim = dim if dim is not None else embedding_dim()
    resolved_model = model or model_name()
    stats = BackfillStats(model=resolved_model, dim=expected_dim)

    if encoder is None:
        encoder = load_encoder(resolved_model)

    pending = await _resolve_pending(pool, rows, fetch, limit)
    stats.total = len(pending)

    start = time.monotonic()
    batch_size = max(1, int(batch_size))
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        await _process_batch(stats, encoder, batch, pool, write, batch_size)

    elapsed = time.monotonic() - start
    stats.duration_s = elapsed
    if elapsed > 0 and stats.embedded > 0:
        stats.throughput = stats.embedded / elapsed
    return stats


# Aliases para compatibilidade com nomes possiveis esperados por testes/CLI.
backfill = backfill_embeddings
embed_chunks = backfill_embeddings
run_backfill = backfill_embeddings

# Aliases publicos para helpers internos (testes podem referenciar sem underscore).
fetch_pending = _fetch_pending
write_embeddings = _write_embeddings


async def main() -> BackfillStats:
    """Ponto de entrada do CLI ``make embed``."""
    pool = await get_pool()
    try:
        return await backfill_embeddings(pool)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
