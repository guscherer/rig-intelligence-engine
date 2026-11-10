"""Testes adversariais do portão de citações (docs/03 §5).

Cobrem as garantias duras do produto: citação obrigatória em frase factual,
resolução de ``[C<n>]`` para ``chunk_id``, e ``evidence_span`` validado como
**substring literal** (não fuzzy). Também os casos de borda da heurística de
"frase factual" (título, lista, transição) e o ``insuficiente`` do positioning.
"""

from __future__ import annotations

import pytest

from rig.core.citations import (
    CitationSpan,
    InvalidEvidenceSpanError,
    UncitedFactualError,
    UnresolvedCitationError,
    find_uncited_sentences,
    parse_citations,
    validate_draft,
    validate_evidence_spans,
)
from rig.graph.nodes.draft import DraftResult, draft
from rig.graph.nodes.positioning import positioning

CHUNKS = [
    {"chunk_id": "c1", "text": "O projeto altera a alíquota do ICMS de 18% para 15%."},
    {"chunk_id": "c2", "text": "A proposta estabelece prazo de 90 dias para adequação."},
    {"chunk_id": "c3", "text": "O texto revoga o artigo 42 da lei anterior."},
]


# ── Resolução de citações ────────────────────────────────────────────────


def test_parse_citations_maps_marker_to_chunk_id() -> None:
    cites = parse_citations("Ref [C1] e [C2].", CHUNKS)
    assert [c.index for c in cites] == [1, 2]
    assert [c.chunk_id for c in cites] == ["c1", "c2"]


def test_citation_out_of_range_is_an_error() -> None:
    draft_text = "O projeto altera a alíquota [C9]."
    with pytest.raises(UnresolvedCitationError):
        parse_citations(draft_text, CHUNKS)
    with pytest.raises(UnresolvedCitationError):
        validate_draft(draft_text, CHUNKS, [])


def test_citation_index_zero_is_an_error() -> None:
    with pytest.raises(UnresolvedCitationError):
        parse_citations("Afirmação [C0].", CHUNKS)


# ── Frase factual sem citação ────────────────────────────────────────────


def test_uncited_factual_sentence_is_rejected() -> None:
    draft_text = "O projeto altera a alíquota do imposto."
    uncited = find_uncited_sentences(draft_text)
    assert len(uncited) == 1
    assert "altera" in uncited[0].text
    with pytest.raises(UncitedFactualError):
        validate_draft(draft_text, CHUNKS, [])


def test_uncited_lists_all_offenders_with_position() -> None:
    draft_text = (
        "O projeto altera a alíquota. "
        "A proposta estabelece prazo de 90 dias. "
        "A multa aumenta para 15%."
    )
    uncited = find_uncited_sentences(draft_text)
    assert len(uncited) == 3
    assert [u.line for u in uncited] == [1, 1, 1]
    assert uncited[0].start < uncited[1].start < uncited[2].start
    with pytest.raises(UncitedFactualError) as exc_info:
        validate_draft(draft_text, CHUNKS, [])
    assert len(exc_info.value.sentences) == 3


# ── Casos de borda da heurística (não são fatos) ─────────────────────────


def test_title_list_and_transition_are_not_flagged() -> None:
    text = (
        "# Nota Técnica\n\n"
        "## Objetivo\n\n"
        "- Reforma tributária\n"
        "- Impacto em ICMS\n\n"
        "Diante do exposto, segue a análise.\n"
    )
    assert find_uncited_sentences(text) == []


# ── evidence_spans como substring literal ────────────────────────────────


def test_evidence_span_one_char_off_fails() -> None:
    # 18% -> 19%: um caractere trocado. Substring literal falha; fuzzy passaria.
    spans = [CitationSpan(citation=1, span="alíquota do ICMS de 19%")]
    with pytest.raises(InvalidEvidenceSpanError):
        validate_evidence_spans(spans, CHUNKS)


def test_evidence_span_extra_whitespace_passes() -> None:
    # strip é permitido e documentado (docstring de citations.py).
    spans = [CitationSpan(citation=1, span="   alíquota do ICMS de 18%   ")]
    validate_evidence_spans(spans, CHUNKS)


def test_evidence_span_missing_chunk_index_is_an_error() -> None:
    spans = [CitationSpan(citation=9, span="qualquer")]
    with pytest.raises(UnresolvedCitationError):
        validate_evidence_spans(spans, CHUNKS)


# ── Portão de tamanho mínimo do evidence_span ───────────────────────────────


def test_evidence_span_too_short_is_rejected() -> None:
    spans = [CitationSpan(citation=1, span="de")]
    with pytest.raises(InvalidEvidenceSpanError) as exc_info:
        validate_evidence_spans(spans, CHUNKS)
    msg = str(exc_info.value)
    assert "2" in msg
    assert str(20) in msg


def test_evidence_span_punctuation_only_is_rejected() -> None:
    spans = [CitationSpan(citation=1, span=".")]
    with pytest.raises(InvalidEvidenceSpanError):
        validate_evidence_spans(spans, CHUNKS)


def test_evidence_span_long_enough_passes() -> None:
    spans = [CitationSpan(citation=1, span="altera a alíquota do ICMS")]
    validate_evidence_spans(spans, CHUNKS)


def test_evidence_span_exactly_min_passes() -> None:
    spans = [CitationSpan(citation=1, span="líquota do ICMS de 1")]
    assert len("líquota do ICMS de 1") == 20
    validate_evidence_spans(spans, CHUNKS)


# ── Minuta válida ────────────────────────────────────────────────────────


def test_valid_draft_is_accepted() -> None:
    text = (
        "## Análise\n\n"
        "O projeto altera a alíquota do ICMS [C1]. "
        "A proposta estabelece prazo de 90 dias [C2]."
    )
    spans = [
        CitationSpan(citation=1, span="altera a alíquota do ICMS"),
        CitationSpan(citation=2, span="estabelece prazo de 90 dias"),
    ]
    validate_draft(text, CHUNKS, spans)


# ── Nós positioning e draft (LLM mockado, sem chamada real) ──────────────


def test_positioning_insufficient_when_corpus_empty() -> None:
    assert positioning(corpus=None).insuficiente is True
    assert positioning(corpus=[]).insuficiente is True
    assert positioning(corpus=[{"chunk_id": "g1", "text": "   "}]).insuficiente is True


def test_positioning_derives_constraints_from_corpus() -> None:
    corpus = [{"chunk_id": "g1", "text": "A empresa adota tom formal e impessoal."}]
    brief = positioning(corpus=corpus)
    assert brief.insuficiente is False
    assert brief.restricoes == ["A empresa adota tom formal e impessoal."]
    assert brief.fonte_restricoes == ["g1"]


def test_draft_node_accepts_valid_mock_output() -> None:
    def gen(prompt: str) -> dict[str, object]:
        return {
            "markdown": (
                "O projeto altera a alíquota do ICMS [C1]. "
                "A proposta estabelece prazo de 90 dias [C2]."
            ),
            "evidence_spans": [
                {"citation": 1, "span": "altera a alíquota do ICMS"},
                {"citation": 2, "span": "estabelece prazo de 90 dias"},
            ],
        }

    result = draft(chunks=CHUNKS, generator=gen)
    assert isinstance(result, DraftResult)
    assert "[C1]" in result.markdown
    assert "[C2]" in result.markdown
    assert len(result.evidence_spans) == 2


def test_draft_node_rejects_uncited_factual_sentence() -> None:
    def gen(prompt: str) -> dict[str, object]:
        return {"markdown": "O projeto altera a alíquota do ICMS.", "evidence_spans": []}

    with pytest.raises(UncitedFactualError):
        draft(chunks=CHUNKS, generator=gen)


def test_draft_node_rejects_non_literal_span() -> None:
    def gen(prompt: str) -> dict[str, object]:
        return {
            "markdown": "O projeto altera a alíquota do ICMS [C1].",
            "evidence_spans": [{"citation": 1, "span": "alíquota do ICMS de 19%"}],
        }

    with pytest.raises(InvalidEvidenceSpanError):
        draft(chunks=CHUNKS, generator=gen)
