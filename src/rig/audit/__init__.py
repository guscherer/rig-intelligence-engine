"""Pacote audit do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from rig.audit.models import Finding, RuleCode, Severity
from rig.audit.nli import (
    DeepSeekNliJudge,
    NliJudge,
    NliJudgeError,
    SentenceVerdict,
    Verdict,
)
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
    "DeepSeekNliJudge",
    "Finding",
    "NliJudge",
    "NliJudgeError",
    "RuleCode",
    "SentenceVerdict",
    "Severity",
    "Verdict",
    "forbidden_language",
    "hard_rules",
    "missing_articles",
    "number_mismatches",
    "orphan_citations",
    "preamble_as_device",
    "uncited_facts",
]
