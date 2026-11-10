"""Checagem global da auditoria (docs/03-agents.md §6.3).

As camadas 1 e 2 olham sentença por sentença; esta olha o documento como um
todo. Quatro checagens puras e determinísticas — zero LLM, zero rede, zero
custo:

1. **Afirmação quantitativa sem fonte** — ``%``/``R$``/"mil"/"milhão"/"bilhão"
   numa frase sem ``[C``.
2. **Promessa de resultado ou prazo ausente da fonte** — a frase afirma um
   prazo ("em 90 dias", "até 2026") que não aparece nos chunks citados. A
   promessa de *resultado* sem termo concreto (ex.: "garantirá a aprovação")
   fica com o NLI (camada 2), que julga a afirmação contra o trecho — aqui não
   há termo determinístico a conferir.
3. **Desvio de escopo** — seção obrigatória do template ausente do documento.
4. **Seção vazia apresentada como concluída** — cabeçalho existe, corpo só tem
   placeholder ou menos que um mínimo de conteúdo.

Tudo devolve ``list[Finding]`` (o tipo do F3.1, ``rig.audit.models``) — não há
tipo paralelo. Severidade: as quatro são REPAIRABLE (voltam ao draft); BLOCKING
é reservado a erro factual objetivo (§6.4), que aqui não se decide sem fonte.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rig.audit.models import Finding, RuleCode, Severity
from rig.core.citations import chunk_text

# Mínimo de caracteres alfanuméricos para uma seção não ser considerada vazia.
# Abaixo disso é placeholder ou corpo sem substância (docs/03 §6.3, checagem 4).
MIN_SECTION_CHARS = 20

# ── Regra 1: afirmação quantitativa sem fonte ────────────────────────────────
# "mil" como palavra inteira para não casar dentro de "milhão"; "milhão"/"bilhão"
# aceitam o plural ("milhões"/"bilhões"). Case-insensitive por construção.
_QUANTITY_MARKER_RE = re.compile(
    r"%|R\$|\bmil\b|\bmilh(?:ão|ões)\b|\bbilh(?:ão|ões)\b",
    re.IGNORECASE,
)

# ── Regra 2: promessa de resultado/prazo ausente da fonte ────────────────────
# Verbos que prometem resultado — sinal de que a frase é promessa, não fato
# (docs/03 §6.3: "garantirá"). Sozinhos não disparam finding: só quando há um
# termo concreto de prazo a conferir (o juízo de "resultado" é do NLI).
_PROMISE_VERB_RE = re.compile(
    r"\b(?:"
    r"garantirá|garantirão|garantiremos|"
    r"assegurará|assegurarão|asseguraremos|"
    r"promete|prometem|prometerá|prometerão|"
    r"entregará|entregarão|entregaremos|"
    r"resultará|resultarão|"
    r"vai\s+garantir|vão\s+garantir|irá\s+garantir"
    r")\b",
    re.IGNORECASE,
)

# Termo concreto de prazo: "em 90 dias", "dentro de 30 dias", "no prazo de 2
# anos", "até 2026", "até 12 meses". Captura o termo ("90 dias", "2026") que
# precisa constar na fonte.
_DEADLINE_TERM_RE = re.compile(
    r"\b(?:em|dentro\s+de|no\s+prazo\s+de|até)\s+"
    r"(\d{1,3}\s+(?:dias?|meses?|anos?)|\d{4})\b",
    re.IGNORECASE,
)

# Fim de frase — mesma convenção de rig.core.citations (ponto entre dígitos não
# separa; "Art." abreviado parte a frase, limitação documentada lá também).
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;]+(?![0-9])")

_CITATION_RE = re.compile(r"\[C(\d+)\]")

# ── Regra 3/4: estrutura de seções ───────────────────────────────────────────
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

# Placeholders de "seção ainda não escrita". "Ponto não coberto pelas fontes
# consultadas" NÃO entra aqui: é a lacuna declarada do draft (§5, regra 4), uma
# seção honestamente marcada como não coberta — não é "vazia apresentada como
# concluída".
_PLACEHOLDER_RE = re.compile(
    r"lorem\s+ipsum|"
    r"\b(?:todo|tbd|fixme|placeholder|a\s+preencher|em\s+branco|sem\s+conteúdo)\b|"
    r"\bxxx+\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SectionTemplate:
    """Lista das seções obrigatórias de um template, na ordem esperada."""

    sections: tuple[str, ...]


@dataclass(frozen=True)
class _Section:
    title: str
    body: str


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(text) if part.strip()]


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _deadline_terms(sentence: str) -> list[str]:
    return [match.group(1) for match in _DEADLINE_TERM_RE.finditer(sentence)]


def _chunks_text(sentence: str, chunks: Sequence[Any]) -> str:
    """Texto dos chunks citados na frase; sem citação válida, o texto de todos."""
    cited = [int(match.group(1)) for match in _CITATION_RE.finditer(sentence)]
    selected = [index for index in cited if 1 <= index <= len(chunks)]
    if not selected:
        selected = list(range(1, len(chunks) + 1))
    return "\n".join(chunk_text(chunks[index - 1]) for index in selected)


def _parse_sections(draft: str) -> list[_Section]:
    """Divide o draft em seções (título + corpo) por cabeçalho Markdown, plano."""
    sections: list[_Section] = []
    title: str | None = None
    body_lines: list[str] = []
    for raw in draft.splitlines():
        line = raw.rstrip("\r")
        match = _HEADING_RE.match(line)
        if match:
            if title is not None:
                sections.append(_Section(title=title, body="\n".join(body_lines)))
            title = match.group(2).strip()
            body_lines = []
        elif title is not None:
            body_lines.append(line)
    if title is not None:
        sections.append(_Section(title=title, body="\n".join(body_lines)))
    return sections


def _normalize_title(title: str) -> str:
    normalized = re.sub(r"^\s*\d{1,3}[.)]\s*", "", title.strip())
    return re.sub(r"\s+", " ", normalized.lower()).strip()


def _meaningful_chars(body: str) -> int:
    cleaned = _PLACEHOLDER_RE.sub(" ", body)
    return sum(1 for char in cleaned if char.isalnum())


def uncited_quantities(draft: str) -> list[Finding]:
    """Frase com marcador quantitativo (%, R$, mil, milhão, bilhão) sem citação."""
    findings: list[Finding] = []
    for sentence in _sentences(draft):
        if _CITATION_RE.search(sentence):
            continue
        markers = _QUANTITY_MARKER_RE.findall(sentence)
        if markers:
            findings.append(
                Finding(
                    code=RuleCode.UNCITED_QUANTITY,
                    sentence=sentence,
                    detail=f"afirmação quantitativa sem citação: {sorted(set(markers))!r}",
                    chunk_id=None,
                    severity=Severity.REPAIRABLE,
                )
            )
    return findings


def unsupported_promises(draft: str, chunks: Sequence[Any]) -> list[Finding]:
    """Prazo/resultado prometido cujo termo concreto não aparece nas fontes citadas."""
    findings: list[Finding] = []
    for sentence in _sentences(draft):
        if not (_PROMISE_VERB_RE.search(sentence) or _DEADLINE_TERM_RE.search(sentence)):
            continue
        source = _normalize_for_match(_chunks_text(sentence, chunks))
        for term in _deadline_terms(sentence):
            if _normalize_for_match(term) not in source:
                findings.append(
                    Finding(
                        code=RuleCode.UNSUPPORTED_PROMISE,
                        sentence=sentence,
                        detail=f"prazo {term!r} não aparece nas fontes citadas",
                        chunk_id=None,
                        severity=Severity.REPAIRABLE,
                    )
                )
    return findings


def missing_sections(draft: str, template: SectionTemplate) -> list[Finding]:
    """Seção obrigatória do template ausente do documento (desvio de escopo)."""
    present = {_normalize_title(section.title) for section in _parse_sections(draft)}
    findings: list[Finding] = []
    for required in template.sections:
        if _normalize_title(required) not in present:
            findings.append(
                Finding(
                    code=RuleCode.MISSING_SECTION,
                    sentence=required,
                    detail=f"seção obrigatória {required!r} ausente do documento",
                    chunk_id=None,
                    severity=Severity.REPAIRABLE,
                )
            )
    return findings


def empty_sections(draft: str, template: SectionTemplate) -> list[Finding]:
    """Seção presente cujo corpo é placeholder ou abaixo do mínimo de conteúdo."""
    required = {_normalize_title(title) for title in template.sections}
    findings: list[Finding] = []
    for section in _parse_sections(draft):
        if _normalize_title(section.title) not in required:
            continue
        if _meaningful_chars(section.body) < MIN_SECTION_CHARS:
            findings.append(
                Finding(
                    code=RuleCode.EMPTY_SECTION,
                    sentence=section.title,
                    detail=(
                        f"seção {section.title!r} presente mas sem conteúdo "
                        f"(menos de {MIN_SECTION_CHARS} caracteres)"
                    ),
                    chunk_id=None,
                    severity=Severity.REPAIRABLE,
                )
            )
    return findings


def global_checks(draft: str, template: SectionTemplate, chunks: Sequence[Any]) -> list[Finding]:
    """Roda as quatro checagens globais e concatena os findings (docs/03 §6.3)."""
    findings: list[Finding] = []
    findings.extend(uncited_quantities(draft))
    findings.extend(unsupported_promises(draft, chunks))
    findings.extend(missing_sections(draft, template))
    findings.extend(empty_sections(draft, template))
    return findings


__all__ = [
    "MIN_SECTION_CHARS",
    "SectionTemplate",
    "empty_sections",
    "global_checks",
    "missing_sections",
    "uncited_quantities",
    "unsupported_promises",
]
