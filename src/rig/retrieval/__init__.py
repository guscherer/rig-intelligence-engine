"""Pacote retrieval do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from rig.retrieval.embed import (
    BackfillStats,
    backfill_embeddings,
    embedding_dim,
    encode_texts,
    load_encoder,
    model_name,
    validate_dimension,
)
from rig.retrieval.fetch import fetch_doc_chunks, fetch_document
from rig.retrieval.search import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_LIMIT,
    RRF_K,
    SearchFilters,
    SearchResult,
    dense_search,
    rerank_results,
    rrf_fuse,
    run_search,
    search,
    sparse_search,
)

__all__ = [
    "DEFAULT_CANDIDATE_K",
    "DEFAULT_LIMIT",
    "RRF_K",
    "BackfillStats",
    "SearchFilters",
    "SearchResult",
    "backfill_embeddings",
    "dense_search",
    "embedding_dim",
    "encode_texts",
    "fetch_doc_chunks",
    "fetch_document",
    "load_encoder",
    "model_name",
    "rerank_results",
    "rrf_fuse",
    "run_search",
    "search",
    "sparse_search",
    "validate_dimension",
]
