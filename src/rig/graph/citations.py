"""Parser de citações ``[C<n>]`` e validação de ``evidence_spans`` literais.

Este módulo é o **portão local** do ``draft`` (docs/03 §5): rejeita em código,
antes de qualquer auditoria com LLM, uma minuta que afirma fato sem rastro.
Três garantias determinísticas e testáveis:

1. **Resolução.** Todo marcador ``[C<n>]`` resolve para o ``chunk_id`` de
   ``chunks[n-1]`` (índice 1-based, como em ``FONTES`` do prompt). Índice fora
   do intervalo é erro — nunca silêncio.
2. **Span literal.** Cada ``evidence_span`` é uma **substring literal** do
   texto do chunk a que aponta, comparada byte a byte após ``strip()``. Sem
   fuzzy, sem normalização: trocar um caractere falha.
3. **Cobertura factual.** Frase factual sem citação é rejeitada, listando
   **todas** as infratoras com posição (linha e offset), não só a primeira.

Heurística de "frase factual" — explícita, NÃO é NLP
-----------------------------------------------------
A segmentação em sentenças é ingênua (``. ! ? ;`` seguido de não-dígito). Uma
sentença é factual — e portanto exige ``[C<n>]`` — quando casa **qualquer**
destas condições:

* **Sinal quantitativo:** contém ao menos um dígito (número, prazo, data,
  percentual, valor monetário).
* **Predicado de fato/obrigação:** contém um verbo de ``_FACTUAL_VERBS``
  (3ª pessoa de verbo jurídico/de efeito). Copulativos ambíguos (``é``,
  ``são``) ficam **de fora** de propósito, para não acionar nomes próprios
  como "São Paulo".

Ficam **excluídas** da exigência, mesmo casando as condições acima:

* **Título Markdown** (linha iniciada por ``#``) — estrutura, não fato.
* **Frase de transição** (prefixo em ``_TRANSITION_STARTS``) — organiza o
  texto, não afirma conteúdo.

Limitações conhecidas (documentadas, não escondidas): abreviação com ponto
("Art.", "Sr.") parte a sentença; ponto entre dígitos é tratado como separador
numérico e não parte. Não há resolução de anáfora nem análise sintática.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

MIN_SPAN_CHARS = 20  # abaixo disso o span não é evidência: é substring acidental

_CITATION_RE = re.compile(r"\[C(\d+)\]")

# Fim de sentença: . ! ? ; — exceto ponto que separa dígitos (milhar/decimal).
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;]+(?![0-9])")

_HEADING_RE = re.compile(r"^#{1,6}\s")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")

# Verbos que afirmam efeito/obrigação. Lista fechada e documentada; ampliá-la é
# uma nova regra de negócio (docs/10 §8).
_FACTUAL_VERBS: frozenset[str] = frozenset(
    {
        "prevê",
        "preveem",
        "estabelece",
        "estabelecem",
        "determina",
        "determinam",
        "dispõe",
        "dispõem",
        "define",
        "definem",
        "institui",
        "instituem",
        "cria",
        "criam",
        "altera",
        "alteram",
        "modifica",
        "modificam",
        "revoga",
        "revogam",
        "amplia",
        "ampliam",
        "restringe",
        "restringem",
        "obriga",
        "obrigam",
        "veda",
        "vedam",
        "proíbe",
        "proíbem",
        "permite",
        "permitem",
        "aplica",
        "aplicam",
        "incide",
        "incidem",
        "exige",
        "exigem",
        "reconhece",
        "reconhecem",
        "reduz",
        "reduzem",
        "aumenta",
        "aumentam",
        "estende",
        "estendem",
        "assegura",
        "asseguram",
        "garante",
        "garantem",
        "confere",
        "conferem",
        "atribui",
        "atribuem",
        "passa",
        "passam",
        "promove",
        "promovem",
    }
)

_FACTUAL_VERB_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(v) for v in _FACTUAL_VERBS) + r")\b",
    re.IGNORECASE,
)

# Prefixos de frases de transição/navegação: organizam, não afirmam conteúdo.
_TRANSITION_STARTS: tuple[str, ...] = (
    "a seguir",
    "neste documento",
    "nesse documento",
    "nesta nota",
    "nesta minuta",
    "diante do exposto",
    "em síntese",
    "em resumo",
    "para tanto",
    "não obstante",
    "no que segue",
    "vale registrar",
    "cumpre observar",
    "cabe destacar",
)


@dataclass(frozen=True)
class Citation:
    """Marcador ``[C<n>]`` resolvido para um ``chunk_id`` concreto."""

    marker: str
    index: int
    chunk_id: str
    position: int


@dataclass(frozen=True)
class UncitedSentence:
    """Frase factual sem citação, com posição no texto da minuta."""

    text: str
    line: int
    start: int
    end: int


class CitationSpan(BaseModel):
    """Trecho literal de um chunk que sustenta uma citação (``citation`` é 1-based)."""

    model_config = ConfigDict(extra="forbid")

    citation: int
    span: str = ""


class CitationError(Exception):
    """Violação do portão de citações (docs/03 §5)."""


class UnresolvedCitationError(CitationError):
    """``[C<n>]`` aponta para índice fora do intervalo de ``chunks``."""


class InvalidEvidenceSpanError(CitationError):
    """``evidence_span`` não é substring literal do texto do chunk."""


class UncitedFactualError(CitationError):
    """Há frase factual sem citação; carrega todas as infratoras."""

    def __init__(self, sentences: Sequence[UncitedSentence]) -> None:
        self.sentences = list(sentences)
        preview = " | ".join(f"L{s.line}: {s.text!r}" for s in self.sentences)
        super().__init__(f"{len(self.sentences)} frase(s) factual(is) sem citação: {preview}")


@dataclass(frozen=True)
class _Sentence:
    text: str
    line: int
    start: int
    end: int


def chunk_id(chunk: Any) -> str:
    """Lê o ``chunk_id`` de qualquer formato de chunk (dict, modelo, objeto)."""
    if isinstance(chunk, dict):
        return str(chunk.get("chunk_id") or chunk.get("id") or "")
    for attr in ("chunk_id", "id"):
        if hasattr(chunk, attr):
            value = getattr(chunk, attr)
            if value is not None:
                return str(value)
    return str(chunk)


def chunk_text(chunk: Any) -> str:
    """Lê o texto de qualquer formato de chunk (dict, modelo, objeto)."""
    if isinstance(chunk, dict):
        return str(chunk.get("text") or chunk.get("chunk_text") or "")
    for attr in ("text", "chunk_text"):
        if hasattr(chunk, attr):
            value = getattr(chunk, attr)
            if value is not None:
                return str(value)
    return ""


def parse_citations(text: str, chunks: Sequence[Any]) -> list[Citation]:
    """Extrai ``[C<n>]`` e resolve cada marcador para ``chunks[n-1].chunk_id``.

    Levanta :class:`UnresolvedCitationError` quando ``n < 1`` ou
    ``n > len(chunks)``.
    """
    citations: list[Citation] = []
    for match in _CITATION_RE.finditer(text):
        index = int(match.group(1))
        if index < 1 or index > len(chunks):
            raise UnresolvedCitationError(
                f"citação {match.group(0)} na posição {match.start()} aponta para "
                f"índice {index}, mas há {len(chunks)} chunk(s)"
            )
        citations.append(
            Citation(
                marker=match.group(0),
                index=index,
                chunk_id=chunk_id(chunks[index - 1]),
                position=match.start(),
            )
        )
    return citations


def _iter_lines(text: str) -> list[tuple[int, str, int]]:
    lines: list[tuple[int, str, int]] = []
    pos = 0
    for line_no, raw in enumerate(text.split("\n"), start=1):
        lines.append((line_no, raw.rstrip("\r"), pos))
        pos += len(raw) + 1
    return lines


def _content_of_line(line: str, line_start: int) -> tuple[str, int]:
    lead = len(line) - len(line.lstrip())
    start = line_start + lead
    body = line[lead:]
    marker = _LIST_MARKER_RE.match(body)
    if marker:
        start += marker.end()
        body = body[marker.end() :]
        lead = len(body) - len(body.lstrip())
        start += lead
        body = body.lstrip()
    return body, start


def _split_with_offsets(content: str, base: int) -> list[tuple[str, int]]:
    parts: list[tuple[str, int]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(content):
        body = content[start : match.start()]
        if body.strip():
            parts.append((body.strip(), base + start))
        start = match.end()
    body = content[start:]
    if body.strip():
        parts.append((body.strip(), base + start))
    return parts


def _iter_sentences(text: str) -> list[_Sentence]:
    sentences: list[_Sentence] = []
    for line_no, line, line_start in _iter_lines(text):
        stripped = line.strip()
        if not stripped or _HEADING_RE.match(stripped):
            continue
        content, content_start = _content_of_line(line, line_start)
        for body, start in _split_with_offsets(content, content_start):
            sentences.append(_Sentence(text=body, line=line_no, start=start, end=start + len(body)))
    return sentences


def _is_transition(text: str) -> bool:
    return text.lower().startswith(_TRANSITION_STARTS)


def _is_factual(text: str) -> bool:
    if _is_transition(text):
        return False
    if re.search(r"\d", text):
        return True
    return _FACTUAL_VERB_RE.search(text) is not None


def find_uncited_sentences(text: str) -> list[UncitedSentence]:
    """Devolve **todas** as frases factuais sem citação, com posição.

    Não levanta; a rejeição é decisão do chamador, que pode listar todas.
    """
    out: list[UncitedSentence] = []
    for sentence in _iter_sentences(text):
        if _is_factual(sentence.text) and not _CITATION_RE.search(sentence.text):
            out.append(
                UncitedSentence(
                    text=sentence.text,
                    line=sentence.line,
                    start=sentence.start,
                    end=sentence.end,
                )
            )
    return out


def _unpack_span(entry: Any) -> tuple[int, str]:
    if isinstance(entry, CitationSpan):
        return entry.citation, entry.span
    if isinstance(entry, dict):
        index = entry.get("citation", entry.get("index", entry.get("n", -1)))
        span = entry.get("span", entry.get("text", ""))
        return int(index if index is not None else -1), str(span)
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return int(entry[0]), str(entry[1])
    for attr in ("citation", "index"):
        if hasattr(entry, attr):
            index = getattr(entry, attr)
            span = getattr(entry, "span", getattr(entry, "text", ""))
            return int(index), str(span)
    raise InvalidEvidenceSpanError(f"evidence_span inválido: {entry!r}")


def normalize_evidence_spans(evidence_spans: Sequence[Any]) -> list[CitationSpan]:
    """Normaliza entradas heterogêneas para a lista tipada de :class:`CitationSpan`."""
    return [
        CitationSpan(citation=idx, span=span) for idx, span in map(_unpack_span, evidence_spans)
    ]


def validate_evidence_spans(evidence_spans: Sequence[Any], chunks: Sequence[Any]) -> None:
    """Valida que cada span é substring literal do texto do chunk (após ``strip``).

    Levanta :class:`UnresolvedCitationError` para índice fora do intervalo e
    :class:`InvalidEvidenceSpanError` para span que não é substring literal,
    para span com menos de :data:`MIN_SPAN_CHARS` caracteres (após ``strip``)
    ou para span composto apenas de pontuação e/ou espaços.
    """
    for entry in evidence_spans:
        index, span = _unpack_span(entry)
        if index < 1 or index > len(chunks):
            raise UnresolvedCitationError(
                f"evidence_span aponta para índice {index}, mas há {len(chunks)} chunk(s)"
            )
        stripped = span.strip()
        if stripped and not any(ch.isalnum() for ch in stripped):
            raise InvalidEvidenceSpanError(
                f"evidence_span da citação [C{index}] é composto apenas de "
                f"pontuação e/ou espaços ({len(stripped)} caracteres)"
            )
        if len(stripped) < MIN_SPAN_CHARS:
            raise InvalidEvidenceSpanError(
                f"evidence_span da citação [C{index}] tem {len(stripped)} "
                f"caracteres, mínimo {MIN_SPAN_CHARS}"
            )
        if stripped not in chunk_text(chunks[index - 1]).strip():
            raise InvalidEvidenceSpanError(
                f"evidence_span da citação [C{index}] não é substring literal do "
                f"chunk {chunk_id(chunks[index - 1])!r}"
            )


def validate_draft(text: str, chunks: Sequence[Any], evidence_spans: Sequence[Any]) -> None:
    """Roda o portão local completo. Levanta na primeira violação.

    Ordem: resolução de citações → spans literais → cobertura factual.
    """
    parse_citations(text, chunks)
    validate_evidence_spans(evidence_spans, chunks)
    uncited = find_uncited_sentences(text)
    if uncited:
        raise UncitedFactualError(uncited)


__all__ = [
    "MIN_SPAN_CHARS",
    "Citation",
    "CitationError",
    "CitationSpan",
    "InvalidEvidenceSpanError",
    "UncitedFactualError",
    "UncitedSentence",
    "UnresolvedCitationError",
    "chunk_id",
    "chunk_text",
    "find_uncited_sentences",
    "normalize_evidence_spans",
    "parse_citations",
    "validate_draft",
    "validate_evidence_spans",
]
