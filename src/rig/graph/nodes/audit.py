"""Nó ``audit`` — as três camadas num portão (docs/03-agents.md §6).

Roda as camadas em ordem — regras determinísticas (§6.1) → checagem global
(§6.3) → NLI por sentença citada (§6.2) — e deriva a decisão via
:func:`rig.audit.policy.decide` (§6.4). O juiz NLI é **injetado** (protocolo
:class:`~rig.audit.nli.NliJudge`): o nó não instancia cliente, então é testável
sem rede.

Orçamento: cada chamada de NLI pode empurrar o ``BudgetState``; se estourar no
meio da auditoria, o resultado é ``BLOCKED`` com motivo explícito — nunca
``PASS`` por falta de verba.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rig.audit import (
    AuditReport,
    Decision,
    Finding,
    NliJudge,
    SectionTemplate,
    SentenceVerdict,
    Severity,
    Verdict,
    decide,
    global_checks,
    hard_rules,
    unsupported_rate,
)
from rig.graph.citations import chunk_text, iter_cited_sentences
from rig.graph.state import BudgetExceededError, BudgetState

# Motivo registrado em ``needed_fixes`` quando o orçamento estoura no meio do NLI.
BUDGET_EXCEEDED_REASON = "orçamento excedido durante a auditoria NLI"

# Template padrão de seções obrigatórias (docs/03 §5: estrutura por seção, não
# texto solto). Sobrescrevível por configuração no runner.
DEFAULT_TEMPLATE = SectionTemplate(sections=("Escopo", "Análise", "Recomendação"))


def _collect_needed_fixes(
    findings: Sequence[Finding],
    verdicts: Sequence[SentenceVerdict],
) -> list[str]:
    """Instruções acionáveis para o draft (docs/03 §6.2-§6.3).

    O ``needed_fix`` das sentenças ``UNSUPPORTED`` vira ``revision_notes`` do
    reparo; o ``detail`` dos findings ``REPAIRABLE`` acompanha, para que a
    revisão conserte também a camada determinística e a global.
    """
    fixes: list[str] = []
    for verdict in verdicts:
        if verdict.verdict == Verdict.UNSUPPORTED and verdict.needed_fix:
            fixes.append(verdict.needed_fix)
    for finding in findings:
        if finding.severity == Severity.REPAIRABLE:
            fixes.append(finding.detail)
    return fixes


async def audit(
    *,
    draft_text: str,
    chunks: Sequence[Any],
    template: SectionTemplate,
    judge: NliJudge,
    repair_cycle: int,
    budget: BudgetState | None = None,
) -> AuditReport:
    """Roda as três camadas e devolve o :class:`AuditReport` com a decisão.

    A ordem é fixa (§6): regras duras, checagem global e NLI por sentença. O
    ``budget`` é checado a cada chamada de NLI; estourou no meio, devolve
    ``BLOCKED`` (nunca ``PASS``), com o motivo em ``needed_fixes``.
    """
    findings = [*hard_rules(draft_text, chunks), *global_checks(draft_text, template, chunks)]
    verdicts: list[SentenceVerdict] = []
    try:
        for sentence, citation in iter_cited_sentences(draft_text, chunks):
            if budget is not None:
                budget.check()
            verdict = await judge.judge(sentence, chunk_text(chunks[citation - 1]), citation)
            verdicts.append(verdict)
        if budget is not None:
            budget.check()
    except BudgetExceededError as exc:
        return AuditReport(
            findings=findings,
            verdicts=verdicts,
            decision=Decision.BLOCKED,
            repair_cycle=repair_cycle,
            needed_fixes=[f"{BUDGET_EXCEEDED_REASON}: {exc}"],
            unsupported_rate_before=unsupported_rate(verdicts),
            unsupported_rate_after=unsupported_rate(verdicts),
        )
    return AuditReport(
        findings=findings,
        verdicts=verdicts,
        decision=decide(findings, verdicts, repair_cycle),
        repair_cycle=repair_cycle,
        needed_fixes=_collect_needed_fixes(findings, verdicts),
        unsupported_rate_before=unsupported_rate(verdicts),
        unsupported_rate_after=unsupported_rate(verdicts),
    )


__all__ = ["BUDGET_EXCEEDED_REASON", "DEFAULT_TEMPLATE", "audit"]
