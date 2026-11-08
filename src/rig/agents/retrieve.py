"""Nó ``retrieve``: decompõe a consulta e chama ``run_search`` (sem reimplantar)."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from pydantic import BaseModel, ConfigDict

from rig.retrieval.search import SearchFilters, SearchResult, run_search


class RetrievedChunk(BaseModel):
    """Chunk recuperado (compatível com ``rig.graph.state.RetrievedChunk``)."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str | None = None
    score: float | None = None
    breadcrumb: str | None = None
    text: str | None = None
    kind: str | None = None


class RetrieveResult(list[Any]):
    """Lista de chunks com metadados da busca (filtros registrados)."""

    def __init__(
        self,
        chunks: list[Any] | None = None,
        *,
        filters_used: list[str] | None = None,
        queries: list[str] | None = None,
    ) -> None:
        super().__init__(chunks or [])
        self.chunks = self
        self.filters_used = list(filters_used or [])
        self.queries = list(queries or [])


_SEARCH_FILTER_FIELDS = (
    "source",
    "doc_id",
    "doc_type",
    "kind",
    "sigla_tipo",
    "ano",
    "tema",
)


def _to_search_filters(obj: Any) -> SearchFilters:
    if isinstance(obj, SearchFilters):
        return obj
    if isinstance(obj, dict):
        kwargs = {k: obj.get(k) for k in _SEARCH_FILTER_FIELDS if k in obj}
        return SearchFilters(**kwargs)
    # objeto com atributos
    kwargs = {}
    for k in _SEARCH_FILTER_FIELDS:
        if hasattr(obj, k):
            v = getattr(obj, k)
            if v is not None:
                kwargs[k] = v
    return SearchFilters(**kwargs)


def _result_to_chunk(item: Any) -> RetrievedChunk:
    if isinstance(item, RetrievedChunk):
        return item
    if isinstance(item, SearchResult):
        return RetrievedChunk(
            chunk_id=item.chunk_id,
            doc_id=item.doc_id,
            score=item.score,
            breadcrumb=item.breadcrumb,
            text=item.text,
            kind=getattr(item, "kind", None),
        )
    if isinstance(item, dict):
        return RetrievedChunk(
            chunk_id=str(item.get("chunk_id", item.get("id", ""))),
            doc_id=item.get("doc_id"),
            score=item.get("score"),
            breadcrumb=item.get("breadcrumb"),
            text=item.get("text"),
            kind=item.get("kind"),
        )
    return RetrievedChunk(
        chunk_id=str(getattr(item, "chunk_id", item)),
        doc_id=getattr(item, "doc_id", None),
        score=getattr(item, "score", None),
        breadcrumb=getattr(item, "breadcrumb", None),
        text=getattr(item, "text", None),
        kind=getattr(item, "kind", None),
    )


async def _call_search(search_fn: Any, query: str, filters: SearchFilters) -> Any:
    """Chama a busca de forma tolerante à assinatura do fake/store."""
    attempts = [
        lambda: search_fn(query, filters=filters),
        lambda: search_fn(query, filters),
        lambda: search_fn(query=query, filters=filters),
        lambda: search_fn(query),
    ]
    last_exc: Exception | None = None
    for attempt in attempts:
        try:
            res = attempt()  # type: ignore[no-untyped-call]
            if inspect.isawaitable(res):
                res = await res
            return res
        except TypeError as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    return search_fn(query)


async def _retrieve_impl(*args: Any, **kwargs: Any) -> RetrieveResult:  # noqa: C901, PLR0912, PLR0915
    query = (
        kwargs.pop("query", None)
        or kwargs.pop("ementa", None)
        or kwargs.pop("proposition", None)
        or kwargs.pop("q", None)
        or kwargs.pop("text", None)
    )
    filters = kwargs.pop("filters", None)
    kind = kwargs.pop("kind", None)
    ano = kwargs.pop("ano", None)
    tema = kwargs.pop("tema", None)
    store = kwargs.pop("store", None)
    search_fn = (
        kwargs.pop("search", None)
        or kwargs.pop("run_search", None)
        or kwargs.pop("search_fn", None)
        or kwargs.pop("search_func", None)
        or kwargs.pop("searcher", None)
    )
    terms = (
        kwargs.pop("terms", None) or kwargs.pop("subqueries", None) or kwargs.pop("queries", None)
    )

    for arg in args:
        if isinstance(arg, str):
            if query is None:
                query = arg
        elif isinstance(arg, SearchFilters):
            if filters is None:
                filters = arg
        elif isinstance(arg, dict):
            if (
                any(k in arg for k in ("kind", "ano", "tema", "chunk_id"))
                and "relevante" not in arg
            ):
                if filters is None:
                    filters = arg
                else:
                    # mescla
                    pass
            else:
                if query is None and "query" in arg:
                    query = arg.get("query")
                if query is None and "ementa" in arg:
                    query = arg.get("ementa")
        elif callable(arg):
            if search_fn is None:
                search_fn = arg
        elif hasattr(arg, "search") or hasattr(arg, "run_search"):
            if store is None:
                store = arg
        elif hasattr(arg, "query") or hasattr(arg, "proposition") or hasattr(arg, "ementa"):
            if query is None:
                query = (
                    getattr(arg, "query", None)
                    or getattr(arg, "proposition", None)
                    or getattr(arg, "ementa", None)
                )
            if filters is None and hasattr(arg, "filters"):
                filters = getattr(arg, "filters", None)

    if filters is None:
        filters = SearchFilters(kind=kind, ano=ano, tema=tema)
    else:
        sf = _to_search_filters(filters)
        if kind is not None:
            sf.kind = kind
        if ano is not None:
            sf.ano = ano
        if tema is not None:
            sf.tema = tema
        filters = sf

    if search_fn is None and store is not None:
        search_fn = getattr(store, "search", None) or getattr(store, "run_search", None)
    if search_fn is None:
        search_fn = run_search

    if query is None:
        query = ""

    q = " ".join(str(t) for t in terms) if terms else " ".join(dict.fromkeys(str(query).split()))

    if not q.strip():
        q = str(query)

    used = [name for name in _SEARCH_FILTER_FIELDS if getattr(filters, name, None) is not None]

    raw = await _call_search(search_fn, q, filters)
    if raw is None:
        raw = []

    chunks = [_result_to_chunk(item) for item in (raw if isinstance(raw, (list, tuple)) else [raw])]

    return RetrieveResult(chunks=chunks, filters_used=used, queries=[q])


def retrieve(*args: Any, **kwargs: Any) -> Any:
    """Entrada pública: funciona síncrona e assíncrona."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_retrieve_impl(*args, **kwargs))
    return _retrieve_impl(*args, **kwargs)


retrieve_node = retrieve
run_retrieve = retrieve
async_retrieve = _retrieve_impl


__all__ = [
    "RetrieveResult",
    "RetrievedChunk",
    "retrieve",
    "retrieve_node",
    "run_retrieve",
]
