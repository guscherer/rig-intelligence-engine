"""Regras duras determinísticas da auditoria (docs/03-agents.md §6.1).

Zero LLM, zero rede, zero custo: seis ``if`` que pegam a maior parte das
alucinações reais antes de gastar um token com NLI. Cada regra é uma função pura
``(draft, chunks) -> list[Finding]``; :func:`hard_rules` concatena as seis.

Severidade (docs/03 §6.4): ``MISSING_ARTICLE`` e ``NUMBER_MISMATCH`` são
``BLOCKING`` — erro factual objetivo que nunca repara sozinho; os outros quatro
são ``REPAIRABLE`` (voltam ao draft). A escolha é fixa, não configuração.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from rig.audit.models import Finding, RuleCode, Severity
from rig.core.citations import chunk_id, chunk_text, find_uncited_sentences

# ── Regra 1: citação órfã ────────────────────────────────────────────────────
# [C<n>] é 1-based (mesma convenção de FONTES no prompt e de rig.graph.citations).
_CITATION_RE = re.compile(r"\[C(\d+)\]")

# ── Regra 2: artigo inexistente ──────────────────────────────────────────────
# No draft o formato é exatamente "Art. N" (docs/03 §6.1); no texto dos chunks
# tolera-se "Art N" (sem ponto), por isso o ".?".
_DRAFT_ARTICLE_RE = re.compile(r"Art\.\s*(\d+)", re.IGNORECASE)
_CHUNK_ARTICLE_RE = re.compile(r"\bArt\.?\s*(\d+)", re.IGNORECASE)

# ── Regra 3: número/data divergente ──────────────────────────────────────────
_NUMBER_RE = re.compile(r"(?:R\$\s*)?\d+[.,]\d+\s*%?")
_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
# Duração inteira: "30 dias", "12 meses", "2 anos" — o caso clássico de
# alucinação de prazo que o _NUMBER_RE (só decimal) não pega. O lookbehind
# `(?<![\d.,])` impede que a fração de um decimal ("3,5 anos" → "5 anos") seja
# lida como duração.
_DURATION_RE = re.compile(
    r"(?<![\d.,])\b\d{1,3}\s+(?:dias?|meses?|anos?|semanas?|horas?)\b", re.IGNORECASE
)
# Prazo *prometido* ("em 90 dias", "até 2026"): domínio da checagem global
# REPAIRABLE ``unsupported_promises`` (§6.3), NÃO do ``number_mismatches``
# (BLOCKING). Mantém a divisão §6.1/§6.3: número assertado divergente bloqueia;
# promessa de prazo ausente da fonte volta ao draft.
_PROMISE_DEADLINE_RE = re.compile(
    r"\b(?:em|dentro\s+de|no\s+prazo\s+de|até)\s+\d{1,3}\s+(?:dias?|meses?|anos?|semanas?|horas?)\b",
    re.IGNORECASE,
)

# ── Regra 5: linguagem proibida ──────────────────────────────────────────────
# Lista fechada e documentada (docs/03 §6.1); espaço para crescer é aqui, nunca
# no corpo da regra. Case-insensitive por construção do _FORBIDDEN_RE abaixo.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "inconstitucional",
    "certamente",
    "garantimos",
)
_FORBIDDEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(phrase) for phrase in FORBIDDEN_PHRASES) + r")\b",
    re.IGNORECASE,
)

# Fim de frase — mesma convenção de rig.graph.citations (ponto entre dígitos não
# separa; serve para devolver a "frase ofensora" das regras 5 e 6).
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;]+(?![0-9])")


def orphan_citations(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """``[C<n>]`` aponta para índice que não existe em ``chunks``."""
    findings: list[Finding] = []
    for match in _CITATION_RE.finditer(draft):
        index = int(match.group(1))
        if index < 1 or index > len(chunks):
            findings.append(
                Finding(
                    code=RuleCode.ORPHAN_CITATION,
                    sentence=match.group(0),
                    detail=(
                        f"citação {match.group(0)} aponta para o índice {index}, "
                        f"mas há {len(chunks)} chunk(s)"
                    ),
                    chunk_id=None,
                    severity=Severity.REPAIRABLE,
                )
            )
    return findings


def missing_articles(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """ "Art. N" citado quando nenhum chunk da fonte alcança esse artigo."""
    max_article = _max_article_in_chunks(chunks)
    findings: list[Finding] = []
    for match in _DRAFT_ARTICLE_RE.finditer(draft):
        number = int(match.group(1))
        if max_article is None or number > max_article:
            reached = "nenhum artigo" if max_article is None else f"Art. {max_article}"
            findings.append(
                Finding(
                    code=RuleCode.MISSING_ARTICLE,
                    sentence=match.group(0),
                    detail=f"cita {match.group(0)}, mas a fonte só alcança {reached}",
                    chunk_id=None,
                    severity=Severity.BLOCKING,
                )
            )
    return findings


def number_mismatches(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """Número/data/duração afirmados no draft que não constam (normalizados) nas fontes."""
    source = "\n".join(chunk_text(chunk) for chunk in chunks)
    draft_numbers = {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(draft)}
    source_numbers = {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(source)}
    draft_dates = {m.group(0) for m in _DATE_RE.finditer(draft)}
    source_dates = {m.group(0) for m in _DATE_RE.finditer(source)}
    # Draft: só duração *assertada* (promessa "em 90 dias" é da checagem global).
    # Fonte: todas as durações — "em 90 dias" na fonte também sustenta um draft
    # que afirme "prazo de 90 dias".
    draft_durations = _asserted_durations(draft)
    source_durations = {_normalize_duration(m.group(0)) for m in _DURATION_RE.finditer(source)}

    findings: list[Finding] = []
    for token in sorted(draft_numbers - source_numbers):
        findings.append(
            Finding(
                code=RuleCode.NUMBER_MISMATCH,
                sentence=token,
                detail=f"número {token!r} não consta nas fontes",
                chunk_id=None,
                severity=Severity.BLOCKING,
            )
        )
    for token in sorted(draft_dates - source_dates):
        findings.append(
            Finding(
                code=RuleCode.NUMBER_MISMATCH,
                sentence=token,
                detail=f"data {token!r} não consta nas fontes",
                chunk_id=None,
                severity=Severity.BLOCKING,
            )
        )
    for token in sorted(draft_durations - source_durations):
        findings.append(
            Finding(
                code=RuleCode.NUMBER_MISMATCH,
                sentence=token,
                detail=f"duração {token!r} não consta nas fontes",
                chunk_id=None,
                severity=Severity.BLOCKING,
            )
        )
    return findings


def uncited_facts(draft: str, _chunks: Sequence[Any]) -> list[Finding]:
    """Frase factual sem citação — reusa o portão local de ``rig.graph.citations``.

    A assinatura é uniforme (``chunks`` vem da interface comum), mas a heurística
    só precisa do texto do draft; a fonte real é :func:`find_uncited_sentences`.
    """
    return [
        Finding(
            code=RuleCode.UNCITED_FACT,
            sentence=uncited.text,
            detail="frase factual sem citação [C<n>]",
            chunk_id=None,
            severity=Severity.REPAIRABLE,
        )
        for uncited in find_uncited_sentences(draft)
    ]


def forbidden_language(draft: str, _chunks: Sequence[Any]) -> list[Finding]:
    """Linguagem proibida (juízo jurídico, promessa, superlativo), case-insensitive."""
    findings: list[Finding] = []
    for match in _FORBIDDEN_RE.finditer(draft):
        findings.append(
            Finding(
                code=RuleCode.FORBIDDEN_LANGUAGE,
                sentence=_sentence_containing(draft, match.start()),
                detail=f"termo proibido: {match.group(0)!r}",
                chunk_id=None,
                severity=Severity.REPAIRABLE,
            )
        )
    return findings


def preamble_as_device(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """Citação a chunk ``kind != "dispositivo"`` usada como se fosse dispositivo.

    Heurística conservadora (recall sobre precisão): qualquer citação a chunk de
    preâmbulo ou anexo é sinalizada. A distinção fina entre "citar o preâmbulo
    como preâmbulo" (ok) e "citar como se fosse artigo" (erro) fica para a camada
    2 (NLI). Chunk sem ``kind`` definido não é sinalizado — não há como afirmar
    que é preâmbulo.
    """
    findings: list[Finding] = []
    for match in _CITATION_RE.finditer(draft):
        index = int(match.group(1))
        if index < 1 or index > len(chunks):
            continue  # órfã: regra 1 já cuida
        kind = _chunk_kind(chunks[index - 1])
        if kind and kind != "dispositivo":
            findings.append(
                Finding(
                    code=RuleCode.PREAMBLE_AS_DEVICE,
                    sentence=_sentence_containing(draft, match.start()),
                    detail=f"cita {match.group(0)} (kind={kind!r}) tratando como dispositivo",
                    chunk_id=chunk_id(chunks[index - 1]),
                    severity=Severity.REPAIRABLE,
                )
            )
    return findings


def hard_rules(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """Roda as seis regras determinísticas e concatena os findings."""
    findings: list[Finding] = []
    findings.extend(orphan_citations(draft, chunks))
    findings.extend(missing_articles(draft, chunks))
    findings.extend(number_mismatches(draft, chunks))
    findings.extend(uncited_facts(draft, chunks))
    findings.extend(forbidden_language(draft, chunks))
    findings.extend(preamble_as_device(draft, chunks))
    return findings


def _max_article_in_chunks(chunks: Sequence[Any]) -> int | None:
    numbers = [int(m.group(1)) for c in chunks for m in _CHUNK_ARTICLE_RE.finditer(chunk_text(c))]
    return max(numbers) if numbers else None


def _asserted_durations(text: str) -> set[str]:
    """Durações inteiras *assertadas* no texto (fora de ``em/até N dias``).

    Prazo prometido ("em 90 dias") é domínio da checagem global REPAIRABLE
    (§6.3), não do ``number_mismatches`` — aqui só entra duração afirmada
    ("prazo de 30 dias").
    """
    promise_spans = [m.span() for m in _PROMISE_DEADLINE_RE.finditer(text)]
    out: set[str] = set()
    for match in _DURATION_RE.finditer(text):
        if any(start <= match.start() < end for start, end in promise_spans):
            continue
        out.add(_normalize_duration(match.group(0)))
    return out


def _normalize_duration(token: str) -> str:
    """Normaliza duração para comparação de igualdade (case/whitespace)."""
    return re.sub(r"\s+", " ", token).strip().lower()


def _normalize_number(token: str) -> str:
    """Normaliza número para comparação de igualdade de string (docs/03 §3).

    Vírgula e ponto são o mesmo separador decimal em texto legal; ``R$`` e ``%``
    são ornamentos que não mudam o valor. Comparar como string — e não float —
    preserva o rastro da fonte.
    """
    return token.replace("R$", "").replace("%", "").replace(",", ".").strip()


def _chunk_kind(chunk: Any) -> str:
    """Lê ``kind`` de qualquer formato de chunk (dict, modelo, objeto)."""
    if isinstance(chunk, dict):
        return str(chunk.get("kind") or "")
    if hasattr(chunk, "kind"):
        value = chunk.kind
        return str(value) if value is not None else ""
    return ""


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    """Divide em frases ``(start, end, body)``, como ``rig.graph.citations``."""
    spans: list[tuple[int, int, str]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        body = text[start : match.start()].strip()
        if body:
            spans.append((start, match.start(), body))
        start = match.end()
    body = text[start:].strip()
    if body:
        spans.append((start, len(text), body))
    return spans


def _sentence_containing(text: str, pos: int) -> str:
    """Devolve a frase que contém a posição ``pos`` (ou o texto inteiro)."""
    for start, end, body in _sentence_spans(text):
        if start <= pos < end:
            return body
    return text.strip()


__all__ = [
    "FORBIDDEN_PHRASES",
    "forbidden_language",
    "hard_rules",
    "missing_articles",
    "number_mismatches",
    "orphan_citations",
    "preamble_as_device",
    "uncited_facts",
]
