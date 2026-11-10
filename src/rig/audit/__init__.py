"""Pacote audit do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from rig.audit.hard_rules import (
    FORBIDDEN_PHRASES,
    audit_draft,
    forbidden_language,
    hard_rules,
    missing_articles,
    number_mismatches,
    orphan_citations,
    preamble_as_device,
    uncited_facts,
)
from rig.audit.models import (
    AuditReport,
    AuditStatus,
    Finding,
    FindingCode,
    SentenceVerdict,
    Severity,
    Verdict,
)

__all__ = [
    "FORBIDDEN_PHRASES",
    "AuditReport",
    "AuditStatus",
    "Finding",
    "FindingCode",
    "SentenceVerdict",
    "Severity",
    "Verdict",
    "audit_draft",
    "forbidden_language",
    "hard_rules",
    "missing_articles",
    "number_mismatches",
    "orphan_citations",
    "preamble_as_device",
    "uncited_facts",
]
