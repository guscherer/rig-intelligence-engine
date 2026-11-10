"""Pacote audit do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from rig.audit.global_checks import (
    MIN_SECTION_CHARS,
    SectionTemplate,
    empty_sections,
    global_checks,
    missing_sections,
    uncited_quantities,
    unsupported_promises,
)
from rig.audit.models import Finding, RuleCode, Severity
from rig.audit.nli import (
    DeepSeekNliJudge,
    NliJudge,
    NliJudgeError,
    SentenceVerdict,
    Verdict,
)
from rig.audit.policy import AuditReport, Decision, decide, unsupported_rate
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
    "MIN_SECTION_CHARS",
    "AuditReport",
    "Decision",
    "DeepSeekNliJudge",
    "Finding",
    "NliJudge",
    "NliJudgeError",
    "RuleCode",
    "SectionTemplate",
    "SentenceVerdict",
    "Severity",
    "Verdict",
    "decide",
    "empty_sections",
    "forbidden_language",
    "global_checks",
    "hard_rules",
    "missing_articles",
    "missing_sections",
    "number_mismatches",
    "orphan_citations",
    "preamble_as_device",
    "uncited_facts",
    "uncited_quantities",
    "unsupported_promises",
    "unsupported_rate",
]
