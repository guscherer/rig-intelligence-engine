"""Pacote audit do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from rig.audit.models import Finding, RuleCode, Severity
from rig.audit.rules import (
    FORBIDDEN_PHRASES,
    forbidden_language,
    hard_rules,
    missing_articles,
    number_mismatches,
    orphan_citations,
    preamble_as_device,
    uncited_facts,
)

__all__ = [
    "FORBIDDEN_PHRASES",
    "Finding",
    "RuleCode",
    "Severity",
    "forbidden_language",
    "hard_rules",
    "missing_articles",
    "number_mismatches",
    "orphan_citations",
    "preamble_as_device",
    "uncited_facts",
]
