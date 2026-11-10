"""Casos adversariais do portão de auditoria (docs/07 F3: "os 15 casos passam").

Cada caso é um JSON em ``tests/fixtures/audit/`` com ``draft``, ``chunks``,
``expected_decision`` e ``expected_codes`` (mais ``nli_verdicts`` opcional para
dirigir o juiz NLI mockado). O teste roda o nó ``audit`` real — as três camadas
(regras duras → checagem global → NLI) + ``decide`` — com juiz falso; sem rede,
sem LLM, sem custo. Todo texto é sintético (ADR-009): PL fictício, nomes
inventados, atribuição no topo de cada fixture.

A asserção é forte: a decisão bate **e** o conjunto de códigos de finding é
**exatamente** o esperado — um finding a mais ou a menos quebra o caso. Isso
impede que uma correção futura mude o veredito sem o teste perceber.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rig.audit import SentenceVerdict, Verdict
from rig.graph.nodes.audit import DEFAULT_TEMPLATE, audit

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "audit"


class _SequenceJudge:
    """Juiz NLI falso que devolve vereditos na ordem (default ``SUPPORTED``)."""

    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0

    async def judge(self, sentence: str, span: str, citation: int) -> SentenceVerdict:
        idx = self.calls
        self.calls += 1
        verdict = self._verdicts[idx] if idx < len(self._verdicts) else "SUPPORTED"
        return SentenceVerdict(
            sentence=sentence,
            citation=citation,
            verdict=Verdict(verdict),
            justification="mock",
            needed_fix=None,
        )


def _load_cases() -> list[tuple[str, dict[str, Any]]]:
    """Carrega todos os JSON de ``tests/fixtures/audit/`` em ordem estável."""
    cases: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        cases.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    return cases


_CASES = _load_cases()


@pytest.mark.parametrize(
    ("case_id", "case"),
    _CASES,
    ids=[case_id for case_id, _ in _CASES],
)
@pytest.mark.asyncio
async def test_adversarial_case(case_id: str, case: dict[str, Any]) -> None:
    """O nó ``audit`` deriva a decisão e os códigos exatamente esperados."""
    assert case.get("synthetic") is True, f"{case_id}: falta marcação de texto sintético"
    judge = _SequenceJudge(case.get("nli_verdicts", ["SUPPORTED"]))
    report = await audit(
        draft_text=case["draft"],
        chunks=case["chunks"],
        template=DEFAULT_TEMPLATE,
        judge=judge,
        repair_cycle=0,
    )
    actual_codes = sorted({finding.code.value for finding in report.findings})
    assert actual_codes == sorted(case["expected_codes"]), (
        f"{case_id}: códigos {actual_codes} != esperado {case['expected_codes']}"
    )
    assert report.decision.value == case["expected_decision"], (
        f"{case_id}: decisão {report.decision.value} != esperada {case['expected_decision']}"
    )


def test_at_least_fifteen_cases() -> None:
    """Aceite: mínimo de 15 casos adversariais em fixtures."""

    assert len(_CASES) >= 15, f"esperava ≥15 casos, há {len(_CASES)}"


def test_every_case_declares_expected_fields() -> None:
    """Cada fixture carrega os quatro campos do contrato (draft/chunks/decision/codes)."""

    for case_id, case in _CASES:
        for field in ("draft", "chunks", "expected_decision", "expected_codes"):
            assert field in case, f"{case_id}: campo obrigatório {field!r} ausente"
