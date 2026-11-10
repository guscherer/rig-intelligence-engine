"""Pacote audit do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from importlib import import_module

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

# ``global`` é palavra reservada do Python: ``from rig.audit.global import …``
# não compila. A checagem global (§6.3) é reexportada por importação dinâmica,
# preservando o caminho canônico src/rig/audit/global.py.
_global = import_module(".global", __package__)

MIN_SECTION_CHARS: int = _global.MIN_SECTION_CHARS
SectionTemplate = _global.SectionTemplate
empty_sections = _global.empty_sections
global_checks = _global.global_checks
missing_sections = _global.missing_sections
uncited_quantities = _global.uncited_quantities
unsupported_promises = _global.unsupported_promises

__all__ = [
    "FORBIDDEN_PHRASES",
    "MIN_SECTION_CHARS",
    "DeepSeekNliJudge",
    "Finding",
    "NliJudge",
    "NliJudgeError",
    "RuleCode",
    "SectionTemplate",
    "SentenceVerdict",
    "Severity",
    "Verdict",
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
]
