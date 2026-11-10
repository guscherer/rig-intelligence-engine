"""Política de saída da auditoria (docs/03-agents.md §6.4), implementada como tabela.

As três camadas (§6.1-§6.3) produzem :class:`~rig.audit.models.Finding` e
:class:`~rig.audit.nli.SentenceVerdict`; este módulo é o portão que decide o
desfecho — :data:`Decision.PASS`, :data:`Decision.REPAIR` ou
:data:`Decision.BLOCKED` — a partir deles. A **precedência** das cinco regras de
:func:`decide` é o contrato: reordená-las muda o comportamento do gate (um
``CONTRADICTED`` na mesma rodada de uma hard rule continua ``BLOCKED``; um
``UNSUPPORTED`` no ciclo 2 nunca repara).

``extra="forbid"`` no :class:`AuditReport` é intencional: campo novo sem
declaração é erro de contrato, não silêncio — a política não pode começar a
produzir campos divergentes sem quebrar o gate.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from rig.audit.models import Finding, Severity
from rig.audit.nli import SentenceVerdict, Verdict


class Decision(StrEnum):
    """Desfecho da auditoria sobre uma minuta (docs/03 §6.4)."""

    PASS = "PASS"  # noqa: S105  # veredito de auditoria, não credencial
    REPAIR = "REPAIR"  # algum UNSUPPORTED e repair_cycle < 2
    BLOCKED = "BLOCKED"  # UNSUPPORTED após 2 ciclos, CONTRADICTED, ou hard rule BLOCKING


class AuditReport(BaseModel):
    """Relatório da auditoria: findings, vereditos e a decisão derivada."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]
    verdicts: list[SentenceVerdict]
    decision: Decision
    repair_cycle: int
    needed_fixes: list[str]  # instruções acionáveis para o draft


def decide(
    findings: Sequence[Finding],
    verdicts: Sequence[SentenceVerdict],
    repair_cycle: int,
) -> Decision:
    """Decide o desfecho aplicando as cinco regras de §6.4, nesta precedência.

    1. qualquer ``Finding`` com ``severity=BLOCKING`` → ``BLOCKED`` (erro factual
       objetivo, nunca repara sozinho);
    2. qualquer veredito ``CONTRADICTED`` → ``BLOCKED`` imediato (não tenta
       reparar contradição);
    3. algum ``UNSUPPORTED`` e ``repair_cycle < 2`` → ``REPAIR``;
    4. algum ``UNSUPPORTED`` e ``repair_cycle >= 2`` → ``BLOCKED``;
    5. resto → ``PASS``.
    """
    if any(finding.severity == Severity.BLOCKING for finding in findings):
        return Decision.BLOCKED
    if any(verdict.verdict == Verdict.CONTRADICTED for verdict in verdicts):
        return Decision.BLOCKED
    if any(verdict.verdict == Verdict.UNSUPPORTED for verdict in verdicts):
        return Decision.REPAIR if repair_cycle < 2 else Decision.BLOCKED
    return Decision.PASS


__all__ = ["AuditReport", "Decision", "decide"]
