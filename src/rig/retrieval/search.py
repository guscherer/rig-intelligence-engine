"""Busca híbrida: dense (HNSW) + sparse (FTS) + RRF + rerank opcional."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from rig.core.db import close_pool, get_pool

_embed_module: Any

try:
    import rig.retrieval.embed as _embed_module
except Exception:  # pragma: no cover
    _embed_module = None

# Constante nomeada (Cormack et al., 2009). Não usar número solto.
RRF_K: int = 60

DEFAULT_CANDIDATE_K: int = 50
DEFAULT_LIMIT: int = 8


@dataclass
class SearchFilters:
    """Filtros de metadado aplicados ANTES do ANN (WHERE no SELECT)."""

    source: str | None = None
    doc_id: str | None = None
    doc_type: str | None = None
    kind: str | None = None
    sigla_tipo: str | None = None
    ano: int | None = None
    tema: str | None = None


@dataclass
class SearchResult:
    """Um dispositivo recuperado, com citação conferível."""

    chunk_id: str
    doc_id: str
    breadcrumb: str
    page: int | None
    score: float
    text: str = ""
    source: str = "camara"
    doc_meta: dict[str, Any] = field(default_factory=dict)


def _filter_sql(filters: SearchFilters, start: int) -> tuple[str, list[Any]]:
    """Monta cláusulas WHERE parametrizadas. Retorna (sql, params)."""
    clauses: list[str] = []
    params: list[Any] = []
    idx = start

    if filters.source is not None:
        clauses.append(f"source = ${idx}")
        params.append(filters.source)
        idx += 1
    if filters.doc_id is not None:
        clauses.append(f"doc_id = ${idx}")
        params.append(filters.doc_id)
        idx += 1
    if filters.doc_type is not None:
        clauses.append(f"doc_type = ${idx}")
        params.append(filters.doc_type)
        idx += 1
    if filters.kind is not None:
        clauses.append(f"kind = ${idx}")
        params.append(filters.kind)
        idx += 1
    if filters.sigla_tipo is not None:
        clauses.append(f"doc_meta->>'sigla_tipo' = ${idx}")
        params.append(filters.sigla_tipo)
        idx += 1
    if filters.ano is not None:
        clauses.append(f"(doc_meta->>'ano')::int = ${idx}")
        params.append(int(filters.ano))
        idx += 1
    if filters.tema is not None:
        clauses.append(f"doc_meta->'temas' @> ${idx}::jsonb")
        params.append(json.dumps([filters.tema], ensure_ascii=False))
        idx += 1

    sql = (" AND " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def _row_to_result(row: Any) -> SearchResult:
    meta_raw = row["doc_meta"]
    if isinstance(meta_raw, str):
        try:
            meta = json.loads(meta_raw)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    elif isinstance(meta_raw, dict):
        meta = meta_raw
    else:
        meta = {}
    score_value = row.get("score", 0.0)
    text_value = row.get("chunk_text", "")
    source_value = row.get("source", "camara")
    return SearchResult(
        chunk_id=str(row["chunk_id"]),
        doc_id=str(row["doc_id"]),
        breadcrumb=str(row["breadcrumb"]),
        page=(int(row["page"]) if row["page"] is not None else None),
        score=float(score_value),
        text=str(text_value),
        source=str(source_value),
        doc_meta=meta,
    )


async def dense_search(
    pool: Any,
    query: str,
    *,
    query_vector: list[float] | None = None,
    encoder: Any = None,
    filters: SearchFilters | None = None,
    limit: int = DEFAULT_CANDIDATE_K,
) -> list[SearchResult]:
    """ANN no HNSW com filtro aplicado antes do ORDER BY."""
    if query_vector is None:
        if encoder is None:
            if _embed_module is None:
                raise RuntimeError("stack de embedding nao instalada")
            encoder = _embed_module.load_encoder()
        if _embed_module is None:
            raise RuntimeError("stack de embedding nao instalada")
        vectors = _embed_module.encode_texts(encoder, [query])
        query_vector = vectors[0]

    filt = filters or SearchFilters()
    vector_str = "[" + ",".join(repr(float(x)) for x in query_vector) + "]"
    filter_sql, filter_params = _filter_sql(filt, start=2)
    params: list[Any] = [vector_str, *filter_params, int(limit)]
    limit_idx = len(params)
    sql = f"""
        SELECT chunk_id, source, doc_id, breadcrumb, page, chunk_text, doc_meta,
               1 - (embedding <=> $1::vector) AS score
          FROM chunks
         WHERE embedding IS NOT NULL{filter_sql}
         ORDER BY embedding <=> $1::vector
         LIMIT ${limit_idx}
    """  # noqa: S608
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [_row_to_result(r) for r in rows]


async def sparse_search(
    pool: Any,
    query: str,
    *,
    filters: SearchFilters | None = None,
    limit: int = DEFAULT_CANDIDATE_K,
) -> list[SearchResult]:
    """FTS via tsv + immutable_unaccent na query."""
    filt = filters or SearchFilters()
    filter_sql, filter_params = _filter_sql(filt, start=2)
    params: list[Any] = [query, *filter_params]
    limit_idx = len(params) + 1
    params.append(int(limit))
    sql = f"""
        SELECT chunk_id, source, doc_id, breadcrumb, page, chunk_text, doc_meta,
               ts_rank_cd(tsv, plainto_tsquery('pt_unaccent',
                           immutable_unaccent($1))) AS score
          FROM chunks
         WHERE tsv @@ plainto_tsquery('pt_unaccent', immutable_unaccent($1)){filter_sql}
         ORDER BY score DESC
         LIMIT ${limit_idx}
    """  # noqa: S608
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [_row_to_result(r) for r in rows]


def rrf_fuse(
    result_lists: list[list[SearchResult]],
    *,
    k: int = RRF_K,
    limit: int | None = None,
) -> list[SearchResult]:
    """Fusão Reciprocal Rank Fusion, determinística (desempate por chunk_id)."""
    fused: dict[str, SearchResult] = {}
    scores: dict[str, float] = {}
    for results in result_lists:
        for rank, result in enumerate(results, start=1):
            contribution = 1.0 / (k + rank)
            if result.chunk_id in scores:
                scores[result.chunk_id] += contribution
            else:
                scores[result.chunk_id] = contribution
                fused[result.chunk_id] = result
    ordered_ids = sorted(scores.keys(), key=lambda cid: (-scores[cid], cid))
    out: list[SearchResult] = []
    for cid in ordered_ids:
        item = fused[cid]
        item.score = scores[cid]
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out


def load_reranker(model: str | None = None) -> Any:
    """Carrega cross-encoder local (lazy). Levanta RuntimeError se indisponível."""
    name = model or os.environ.get("MODEL_RERANKER", "BAAI/bge-reranker-v2-m3")
    try:
        module = __import__("sentence_transformers", fromlist=["CrossEncoder"])
        cross_encoder_cls = module.CrossEncoder
    except ImportError as exc:
        raise RuntimeError("stack de rerank nao instalada; rode `uv sync --extra embed`") from exc
    return cross_encoder_cls(name, model_kwargs={"low_cpu_mem_usage": True})


def rerank_results(
    reranker: Any,
    query: str,
    candidates: list[SearchResult],
    *,
    limit: int | None = None,
) -> list[SearchResult]:
    """Reordena candidatos com cross-encoder local."""
    if not candidates:
        return []
    pairs = [(query, c.text) for c in candidates]
    try:
        raw_scores = reranker.predict(pairs)
    except TypeError:
        raw_scores = reranker.predict(pairs, batch_size=16)
    scored: list[tuple[float, str, SearchResult]] = []
    for result, value in zip(candidates, raw_scores, strict=True):
        result.score = float(value)
        scored.append((result.score, result.chunk_id, result))
    scored.sort(key=lambda item: (-item[0], item[1]))
    ordered = [item[2] for item in scored]
    if limit is not None:
        ordered = ordered[:limit]
    return ordered


async def search(  # noqa: PLR0913
    pool: Any,
    query: str,
    *,
    mode: str = "rrf",
    filters: SearchFilters | None = None,
    limit: int = DEFAULT_LIMIT,
    candidate_k: int = DEFAULT_CANDIDATE_K,
    encoder: Any = None,
    query_vector: list[float] | None = None,
    reranker: Any = None,
    rerank: bool | None = None,
) -> list[SearchResult]:
    """Pipeline híbrido selecionável: dense / sparse / rrf / rrf+rerank."""
    filt = filters or SearchFilters()
    do_rerank = rerank if rerank is not None else (mode in {"rrf+rerank", "rerank"})
    modes_dense = {"dense", "rrf", "rrf+rerank", "rerank"}
    modes_sparse = {"sparse", "rrf", "rrf+rerank", "rerank"}

    dense_results: list[SearchResult] = []
    sparse_results: list[SearchResult] = []

    if mode in modes_dense:
        dense_results = await dense_search(
            pool,
            query,
            query_vector=query_vector,
            encoder=encoder,
            filters=filt,
            limit=candidate_k,
        )
    if mode in modes_sparse:
        sparse_results = await sparse_search(pool, query, filters=filt, limit=candidate_k)

    if mode == "dense":
        candidates = dense_results
    elif mode == "sparse":
        candidates = sparse_results
    else:
        lists = [lst for lst in (dense_results, sparse_results) if lst]
        candidates = rrf_fuse(lists, limit=candidate_k)

    if do_rerank:
        if reranker is None:
            try:
                reranker = load_reranker()
            except RuntimeError:
                reranker = None
        if reranker is not None:
            candidates = rerank_results(reranker, query, candidates, limit=None)

    return candidates[:limit]


async def run_search(
    query: str,
    *,
    mode: str = "dense",
    filters: SearchFilters | None = None,
    limit: int = DEFAULT_LIMIT,
    candidate_k: int = DEFAULT_CANDIDATE_K,
) -> list[SearchResult]:
    """Ponto de entrada do CLI `make search`."""
    pool = await get_pool()
    try:
        return await search(
            pool,
            query,
            mode=mode,
            filters=filters,
            limit=limit,
            candidate_k=candidate_k,
        )
    finally:
        await close_pool()
