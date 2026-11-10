"""Testes da política de saída da auditoria (docs/03-agents.md §6.4).

Cobre as cinco regras de :func:`decide` em ordem e as precedências que importam:
BLOCKING vence UNSUPPORTED; CONTRADICTED vence REPAIR; ciclo 2 não repara. Toda
a tabela é testada, não só cada linha isolada.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rig.audit import (
    AuditReport,
    Decision,
    Finding,
    RuleCode,
    SentenceVerdict,
    Severity,
    Verdict,
    decide,
    unsupported_rate,
)


def _finding(severity: Severity, code: RuleCode) -> Finding:
    return Finding(code=code, sentence="x", detail="y", chunk_id=None, severity=severity)


def _blocking() -> Finding:
    return _finding(Severity.BLOCKING, RuleCode.NUMBER_MISMATCH)


def _repairable() -> Finding:
    return _finding(Severity.REPAIRABLE, RuleCode.FORBIDDEN_LANGUAGE)


def _verdict(verdict: Verdict, needed_fix: str | None = None) -> SentenceVerdict:
    return SentenceVerdict(
        sentence="x",
        citation=1,
        verdict=verdict,
        justification="j",
        needed_fix=needed_fix,
    )


# ── Regra 1: BLOCKING nunca repara ───────────────────────────────────────────


def test_blocking_finding_blocks() -> None:
    assert decide([_blocking()], [], 0) == Decision.BLOCKED


def test_blocking_wins_over_unsupported() -> None:
    # Erro factual objetivo na mesma rodada de um UNSUPPORTED continua BLOCKED.
    assert decide([_blocking()], [_verdict(Verdict.UNSUPPORTED)], 0) == Decision.BLOCKED


# ── Regra 2: CONTRADICTED bloqueia imediato ───────────────────────────────────


def test_contradicted_blocks_immediately() -> None:
    assert decide([], [_verdict(Verdict.CONTRADICTED)], 0) == Decision.BLOCKED


def test_contradicted_wins_over_repair() -> None:
    # CONTRADICTED na mesma rodada de um UNSUPPORTED (que repararia) continua BLOCKED.
    assert (
        decide([], [_verdict(Verdict.UNSUPPORTED), _verdict(Verdict.CONTRADICTED)], 0)
        == Decision.BLOCKED
    )


# ── Regras 3 e 4: UNSUPPORTED repara até o ciclo 1, bloqueia no ciclo 2 ───────


def test_unsupported_cycle0_repairs() -> None:
    assert decide([], [_verdict(Verdict.UNSUPPORTED)], 0) == Decision.REPAIR


def test_unsupported_cycle1_repairs() -> None:
    assert decide([], [_verdict(Verdict.UNSUPPORTED)], 1) == Decision.REPAIR


def test_unsupported_cycle2_does_not_repair() -> None:
    assert decide([], [_verdict(Verdict.UNSUPPORTED)], 2) == Decision.BLOCKED


# ── Regra 5: resto → PASS ─────────────────────────────────────────────────────


def test_clean_passes() -> None:
    assert decide([], [_verdict(Verdict.SUPPORTED), _verdict(Verdict.PARTIAL)], 0) == Decision.PASS


def test_no_findings_no_verdicts_passes() -> None:
    assert decide([], [], 0) == Decision.PASS


def test_repairable_finding_repairs() -> None:
    # §6.4: finding REPAIRABLE (ex.: linguagem proibida) volta ao draft, não
    # passa como limpo. Regra 3: REPAIRABLE e cycle < 2 → REPAIR.
    assert decide([_repairable()], [_verdict(Verdict.SUPPORTED)], 0) == Decision.REPAIR


def test_repairable_finding_blocks_at_cycle2() -> None:
    # REPAIRABLE que persiste após 2 ciclos bloqueia (mesma regra do UNSUPPORTED).
    assert decide([_repairable()], [_verdict(Verdict.SUPPORTED)], 2) == Decision.BLOCKED


# ── Taxa de UNSUPPORTED (critério de pronto do F3, docs/07) ──────────────────


def test_unsupported_rate_is_fraction_of_judged_sentences() -> None:
    assert unsupported_rate([_verdict(Verdict.UNSUPPORTED)]) == 1.0
    assert unsupported_rate([_verdict(Verdict.SUPPORTED)]) == 0.0
    assert unsupported_rate([_verdict(Verdict.UNSUPPORTED), _verdict(Verdict.SUPPORTED)]) == 0.5


def test_unsupported_rate_empty_verdicts_is_zero() -> None:
    assert unsupported_rate([]) == 0.0


# ── Contrato do relatório ─────────────────────────────────────────────────────


def test_audit_report_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AuditReport(
            findings=[],
            verdicts=[],
            decision=Decision.PASS,
            repair_cycle=0,
            needed_fixes=[],
            unsupported_rate_before=0.0,
            unsupported_rate_after=0.0,
            campo_inventado="não deveria existir",
        )


def test_audit_report_roundtrip() -> None:
    report = AuditReport(
        findings=[_repairable()],
        verdicts=[_verdict(Verdict.SUPPORTED)],
        decision=Decision.PASS,
        repair_cycle=0,
        needed_fixes=[],
        unsupported_rate_before=0.0,
        unsupported_rate_after=0.0,
    )
    assert report.decision == Decision.PASS
    assert report.repair_cycle == 0
    assert len(report.findings) == 1
