"""Modelos tipados do auditor (docs/03-agents.md §6).

Compartilhados pelas três camadas: regras duras (§6.1), NLI (§6.2) e checagem
global (§6.3). Um tipo só, definido aqui. ``extra="forbid"`` é intencional:
campo novo sem declaração é erro de contrato, não silêncio.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class FindingCode(StrEnum):
    """Código estável de cada regra dura da camada 1 (e extensões das demais)."""

    ORPHAN_CITATION = "orphan_citation"  # [C9] com índice inexistente
    MISSING_ARTICLE = "missing_article"  # "Art. 42" quando a fonte só vai até Art. 30
    NUMBER_MISMATCH = "number_mismatch"  # número/data divergente entre afirmação e fonte
    UNCITED_FACT = "uncited_fact"  # frase factual sem [C
    FORBIDDEN_LANGUAGE = "forbidden_language"  # "inconstitucional", "certamente", "garantimos"
    PREAMBLE_AS_DEVICE = "preamble_as_device"  # cita preâmbulo como se fosse dispositivo


class Severity(StrEnum):
    """Severidade do finding. A política de saída (§6.4) decide o desfecho por aqui."""

    BLOCKING = "blocking"  # erro factual objetivo: nunca repara sozinho (§6.4)
    REPAIRABLE = "repairable"  # pode voltar ao draft


class Verdict(StrEnum):
    """Veredito do juiz NLI: o trecho sustenta, sustenta em parte, não sustenta ou contradiz."""

    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class AuditStatus(StrEnum):
    """Status final do auditor (docs/03 §6.4)."""

    PASS = "PASS"  # noqa: S105
    REPAIR = "REPAIR"
    BLOCKED = "BLOCKED"


class Finding(BaseModel):
    """Um problema encontrado pela auditoria, com contexto suficiente para o reparo."""

    model_config = ConfigDict(extra="forbid")

    code: FindingCode
    severity: Severity
    sentence_index: int
    detail: str
    needed_fix: str


class SentenceVerdict(BaseModel):
    """Veredito do juiz para uma sentença citada, com contexto para o reparo."""

    model_config = ConfigDict(extra="forbid")

    sentence: str
    sentence_index: int = 0
    citation: int
    verdict: Verdict
    justification: str
    needed_fix: str | None


class AuditReport(BaseModel):
    """Saída do auditor: veredito por frase e lista de reparos endereçáveis."""

    model_config = ConfigDict(extra="forbid")

    status: AuditStatus
    findings: list[Finding]
    verdicts: list[SentenceVerdict]
    reasons: list[str]
    needed_fixes: list[str]
    stats: dict[str, Any]


__all__ = [
    "AuditReport",
    "AuditStatus",
    "Finding",
    "FindingCode",
    "SentenceVerdict",
    "Severity",
    "Verdict",
]
