"""Testes unitários da busca híbrida (sem rede)."""

from __future__ import annotations

from rig.retrieval.search import (
    RRF_K,
    SearchFilters,
    SearchResult,
    _filter_sql,
    rerank_results,
    rrf_fuse,
)


def _res(cid: str, score: float = 0.0) -> SearchResult:
    return SearchResult(
        chunk_id=cid, doc_id="d1", breadcrumb="Art. 1", page=1, score=score, text="t"
    )


def test_rrf_monotonic() -> None:
    dense = [_res("a"), _res("b")]
    sparse = [_res("a"), _res("c")]
    fused = rrf_fuse([dense, sparse])
    scores = {r.chunk_id: r.score for r in fused}
    # "a" aparece nas duas listas -> score maior que quem aparece em uma.
    assert scores["a"] > scores["b"]
    assert scores["a"] > scores["c"]


def test_rrf_deterministic_tie_break() -> None:
    # duas listas idênticas com mesma contribuição -> desempate por chunk_id.
    dense = [_res("z"), _res("a")]
    fused = rrf_fuse([dense])
    # apenas ordenação por score desc; "a" e "z" têm ranks diferentes, mas tie-break estável.
    assert [r.chunk_id for r in fused] == ["z", "a"]
    # empate artificial: mesma lista duplicada com ids invertidos não quebra.
    tied = rrf_fuse([[_res("m"), _res("n")], [_res("n"), _res("m")]])
    # scores iguais -> ordem por chunk_id
    assert [r.chunk_id for r in tied] == ["m", "n"]


def test_rrf_k_constant_named() -> None:
    assert RRF_K == 60


def test_filter_sql_reduces() -> None:
    filt = SearchFilters(kind="dispositivo")
    sql, params = _filter_sql(filt, start=2)
    assert "kind = $2" in sql
    assert params == ["dispositivo"]

    empty_sql, empty_params = _filter_sql(SearchFilters(), start=1)
    assert empty_sql == ""
    assert empty_params == []


def test_rerank_does_not_drop_recall() -> None:
    cands = [_res("x", 0.1), _res("y", 0.2), _res("z", 0.3)]

    class FakeReranker:
        def predict(self, pairs):
            # preserva a ordem original (scores decrescentes no mesmo sentido)
            return [0.1, 0.2, 0.3]

    out = rerank_results(FakeReranker(), "q", cands, limit=3)
    # top-1 continua sendo o de maior score original (z) quando reranker concorda.
    assert out[0].chunk_id == "z"
    assert len(out) == 3


def test_rerank_tie_break_deterministic() -> None:
    cands = [_res("b"), _res("a")]

    class FakeReranker:
        def predict(self, pairs):
            return [0.5, 0.5]

    out = rerank_results(FakeReranker(), "q", cands, limit=2)
    assert [r.chunk_id for r in out] == ["a", "b"]
