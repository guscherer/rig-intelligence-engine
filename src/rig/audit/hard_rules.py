"""Regras duras determinísticas da auditoria (docs/03-agents.md §6.1).

Zero LLM, zero rede, zero custo: seis ``if`` que pegam a maior parte das
alucinações reais antes de gastar um token com NLI. Cada regra é uma função
pura ``(draft, chunks) -> list[Finding]``; :func:`hard_rules` concatena as seis
e :func:`audit_draft` monta o :class:`AuditReport`.

Este arquivo é grande porque é uma **tabela de regras** (docs/10 §2): cada
regra é uma função curta e independente, e o tamanho vem da quantidade, não da
complexidade. Exceção legítima documentada.

Fronteira (docs/10 §1): este pacote importa apenas ``rig.core``. A resolução de
``[C<n>]`` contra ``chunks`` é feita aqui por regex simples e leitura tolerante
de formato de chunk (dict/objeto/atributo) — **não** reusa ``rig.graph.citations``
(pacote superior), para não violar a fronteira. Duplicação intencional e
documentada: a heurística de frase factual é reimplementada aqui.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from rig.audit.models import (
    AuditReport,
    AuditStatus,
    Finding,
    FindingCode,
    Severity,
)

# ── Regex compartilhadas ──────────────────────────────────────────────────────
_CITATION_RE = re.compile(r"\[C(\d+)\]")
_DRAFT_ARTICLE_RE = re.compile(r"Art\.\s*(\d+)", re.IGNORECASE)
_CHUNK_ARTICLE_RE = re.compile(r"\bArt\.?\s*(\d+)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;]+(?![0-9])")

# ── Regra 5: linguagem proibida ───────────────────────────────────────────────
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "inconstitucional",
    "certamente",
    "garantimos",
)
_FORBIDDEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(phrase) for phrase in FORBIDDEN_PHRASES) + r")\b",
    re.IGNORECASE,
)

# ── Regra 4: frase factual sem citação ────────────────────────────────────────
_HEADING_RE = re.compile(r"^#{1,6}\s")
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
    "ponto não coberto",
)
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


# ── Helpers de leitura tolerante de chunk ─────────────────────────────────────


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        value = chunk.get("text", chunk.get("chunk_text", ""))
        return "" if value is None else str(value)
    if hasattr(chunk, "text"):
        value = chunk.text
        if value is not None:
            return str(value)
    if hasattr(chunk, "chunk_text"):
        value = chunk.chunk_text
        if value is not None:
            return str(value)
    return ""


def _chunk_kind(chunk: Any) -> str:
    if isinstance(chunk, dict):
        value = chunk.get("kind")
        return "" if value is None else str(value)
    if hasattr(chunk, "kind"):
        value = chunk.kind
        return "" if value is None else str(value)
    return ""


def _chunk_id(chunk: Any) -> str:
    if isinstance(chunk, dict):
        value = chunk.get("chunk_id", chunk.get("id"))
        return "" if value is None else str(value)
    if hasattr(chunk, "chunk_id"):
        value = chunk.chunk_id
        if value is not None:
            return str(value)
    if hasattr(chunk, "id"):
        value = chunk.id
        if value is not None:
            return str(value)
    return ""


# ── Helpers de sentença ───────────────────────────────────────────────────────


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
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


def _sentence_index_at(text: str, pos: int) -> int:
    for idx, (start, end, _body) in enumerate(_sentence_spans(text)):
        if start <= pos < end:
            return idx
    spans = _sentence_spans(text)
    return len(spans) - 1 if spans else 0


def _sentence_containing(text: str, pos: int) -> str:
    for start, end, body in _sentence_spans(text):
        if start <= pos < end:
            return body
    return text.strip()


def _is_transition(text: str) -> bool:
    return text.lower().lstrip().startswith(_TRANSITION_STARTS)


def _is_factual(text: str) -> bool:
    if _is_transition(text):
        return False
    if re.search(r"\d", text):
        return True
    return _FACTUAL_VERB_RE.search(text) is not None


# ── Regra 1: citação órfã ─────────────────────────────────────────────────────


def orphan_citations(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """``[C<n>]`` aponta para índice que não existe em ``chunks`` (1-based)."""
    findings: list[Finding] = []
    for match in _CITATION_RE.finditer(draft):
        index = int(match.group(1))
        if index < 1 or index > len(chunks):
            findings.append(
                Finding(
                    code=FindingCode.ORPHAN_CITATION,
                    severity=Severity.REPAIRABLE,
                    sentence_index=_sentence_index_at(draft, match.start()),
                    detail=(
                        f"citação [C{index}] aponta para o índice {index}, "
                        f"mas há {len(chunks)} chunk(s)"
                    ),
                    needed_fix=f"remover ou corrigir a citação [C{index}] inexistente",
                )
            )
    return findings


# ── Regra 2: artigo inexistente ───────────────────────────────────────────────


def _max_article_in_chunks(chunks: Sequence[Any]) -> int | None:
    numbers = [int(m.group(1)) for c in chunks for m in _CHUNK_ARTICLE_RE.finditer(_chunk_text(c))]
    return max(numbers) if numbers else None


def missing_articles(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """``Art. N`` citado quando nenhum chunk da fonte alcança esse artigo."""
    max_article = _max_article_in_chunks(chunks)
    findings: list[Finding] = []
    for match in _DRAFT_ARTICLE_RE.finditer(draft):
        number = int(match.group(1))
        if max_article is None or number > max_article:
            reached = "nenhum artigo" if max_article is None else f"Art. {max_article}"
            findings.append(
                Finding(
                    code=FindingCode.MISSING_ARTICLE,
                    severity=Severity.BLOCKING,
                    sentence_index=_sentence_index_at(draft, match.start()),
                    detail=f"cita Art. {number}, mas a fonte só alcança {reached}",
                    needed_fix=f"corrigir a referência Art. {number} (fonte alcança {reached})",
                )
            )
    return findings


# ── Regra 3: número/data divergente ───────────────────────────────────────────


def _normalize_number(token: str) -> str:
    """Normaliza número para comparação de igualdade de string (docs/03 §3).

    Remove separadores de milhar e decimal (``.`` e ``,``) e ornamentos
    (``R$``, ``%``), deixando só dígitos. Assim ``1.000`` e ``1000`` comparam
    iguais (o ponto é tratado como separador de milhar, convenção do texto
    legal brasileiro), e ``3,5`` e ``3.5`` comparam iguais (vírgula e ponto
    são o mesmo separador decimal). Comparar como string — e não float —
    preserva o rastro da fonte.
    """
    return token.replace("R$", "").replace("%", "").replace(".", "").replace(",", "").strip()


def _extract_numbers(text: str) -> set[str]:
    masked = _DATE_RE.sub(" ", text)
    return {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(masked)}


def number_mismatches(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """Número/data afirmado no draft que não consta (normalizado) nas fontes."""
    source = "\n".join(_chunk_text(c) for c in chunks)
    draft_numbers = _extract_numbers(draft)
    source_numbers = _extract_numbers(source)
    draft_dates = {m.group(0) for m in _DATE_RE.finditer(draft)}
    source_dates = {m.group(0) for m in _DATE_RE.finditer(source)}

    findings: list[Finding] = []
    for token in sorted(draft_numbers - source_numbers):
        findings.append(
            Finding(
                code=FindingCode.NUMBER_MISMATCH,
                severity=Severity.BLOCKING,
                sentence_index=0,
                detail=f"número {token!r} não consta nas fontes",
                needed_fix=f"corrigir o número {token!r} conforme as fontes",
            )
        )
    for token in sorted(draft_dates - source_dates):
        findings.append(
            Finding(
                code=FindingCode.NUMBER_MISMATCH,
                severity=Severity.BLOCKING,
                sentence_index=0,
                detail=f"data {token!r} não consta nas fontes",
                needed_fix=f"corrigir a data {token!r} conforme as fontes",
            )
        )
    return findings


# ── Regra 4: frase factual sem citação ────────────────────────────────────────


def uncited_facts(draft: str, _chunks: Sequence[Any]) -> list[Finding]:
    """Frase factual sem citação ``[C<n>]``."""
    findings: list[Finding] = []
    for idx, (_start, _end, body) in enumerate(_sentence_spans(draft)):
        if _is_factual(body) and not _CITATION_RE.search(body):
            findings.append(
                Finding(
                    code=FindingCode.UNCITED_FACT,
                    severity=Severity.REPAIRABLE,
                    sentence_index=idx,
                    detail="frase factual sem citação [C<n>]",
                    needed_fix="adicionar citação [C<n>] à frase ou remover a afirmação",
                )
            )
    return findings


# ── Regra 5: linguagem proibida ───────────────────────────────────────────────


def forbidden_language(draft: str, _chunks: Sequence[Any]) -> list[Finding]:
    """Linguagem proibida (juízo jurídico, promessa, superlativo), case-insensitive."""
    findings: list[Finding] = []
    for match in _FORBIDDEN_RE.finditer(draft):
        findings.append(
            Finding(
                code=FindingCode.FORBIDDEN_LANGUAGE,
                severity=Severity.REPAIRABLE,
                sentence_index=_sentence_index_at(draft, match.start()),
                detail=f"termo proibido: {match.group(0)!r}",
                needed_fix=f"remover o termo proibido {match.group(0)!r}",
            )
        )
    return findings


# ── Regra 6: preâmbulo como dispositivo ───────────────────────────────────────


def preamble_as_device(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """Citação a chunk ``kind != "dispositivo"`` usada como se fosse dispositivo."""
    findings: list[Finding] = []
    for match in _CITATION_RE.finditer(draft):
        index = int(match.group(1))
        if index < 1 or index > len(chunks):
            continue  # órfã: regra 1 já cuida
        kind = _chunk_kind(chunks[index - 1])
        if kind and kind != "dispositivo":
            findings.append(
                Finding(
                    code=FindingCode.PREAMBLE_AS_DEVICE,
                    severity=Severity.REPAIRABLE,
                    sentence_index=_sentence_index_at(draft, match.start()),
                    detail=f"cita [C{index}] (kind={kind!r}) tratando como dispositivo",
                    needed_fix=f"não citar [C{index}] como dispositivo (kind={kind!r})",
                )
            )
    return findings


# ── Agregador e entrada pública ───────────────────────────────────────────────


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


def audit_draft(draft: str, chunks: Sequence[Any]) -> AuditReport:
    """Camada 1 do auditor: regras determinísticas, custo zero.

    Devolve um :class:`AuditReport` com os findings da camada 1. Camadas 2
    (NLI) e 3 (global) são acrescentadas por outros módulos; aqui o status é
    derivado apenas dos findings duros (§6.4): BLOCKING → BLOCKED, findings
    reparáveis → REPAIR, sem findings → PASS.
    """
    findings = hard_rules(draft, chunks)
    blocking = any(f.severity == Severity.BLOCKING for f in findings)
    if not findings:
        status = AuditStatus.PASS
    elif blocking:
        status = AuditStatus.BLOCKED
    else:
        status = AuditStatus.REPAIR
    return AuditReport(
        status=status,
        findings=findings,
        verdicts=[],
        reasons=[f.detail for f in findings],
        needed_fixes=[f.needed_fix for f in findings],
        stats={
            "findings": len(findings),
            "blocking": sum(1 for f in findings if f.severity == Severity.BLOCKING),
            "repairable": sum(1 for f in findings if f.severity == Severity.REPAIRABLE),
        },
    )


__all__ = [
    "FORBIDDEN_PHRASES",
    "audit_draft",
    "forbidden_language",
    "hard_rules",
    "missing_articles",
    "number_mismatches",
    "orphan_citations",
    "preamble_as_device",
    "uncited_facts",
]
