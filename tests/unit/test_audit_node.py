"""Testes do nó ``audit`` (docs/03-agents.md §6) com juiz mockado, sem rede.

O juiz NLI é injetado (protocolo ``NliJudge``) e conta as chamadas; o nó é
testado isolado (uma passada) e o laço de reparo é testado via ``run_pipeline``
com gerador e juiz falsos — o contador do gerador prova exatamente quantos
reparos rodaram. Todo texto é sintético (ADR-009).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from rig.adapters import Generation, Usage
from rig.audit import Decision, SentenceVerdict, Verdict
from rig.core.config import Settings
from rig.graph.nodes.audit import DEFAULT_TEMPLATE, audit
from rig.graph.runner import run_pipeline
from rig.graph.state import BudgetState


class _FakeJudge:
    """Juiz NLI falso: devolve um veredito fixo e conta as chamadas."""

    def __init__(self, verdict: str, needed_fix: str | None = None) -> None:
        self._verdict = verdict
        self._needed_fix = needed_fix
        self.calls = 0

    async def judge(self, sentence: str, span: str, citation: int) -> SentenceVerdict:
        self.calls += 1
        return SentenceVerdict(
            sentence=sentence,
            citation=citation,
            verdict=Verdict(self._verdict),
            justification="mock",
            needed_fix=self._needed_fix,
        )


CHUNK = {"chunk_id": "c1", "text": "A norma prevê adaptação em 90 dias.", "kind": "dispositivo"}


# ── Nó isolado (uma passada) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_repairs_at_cycle0_with_needed_fixes() -> None:
    judge = _FakeJudge("UNSUPPORTED", needed_fix="Citar o trecho que define o prazo.")
    report = await audit(
        draft_text="A norma estabelece normas gerais [C1].",
        chunks=[CHUNK],
        template=DEFAULT_TEMPLATE,
        judge=judge,
        repair_cycle=0,
    )
    assert report.decision == Decision.REPAIR
    assert report.repair_cycle == 0
    assert any("Citar o trecho" in fix for fix in report.needed_fixes)


@pytest.mark.asyncio
async def test_contradicted_blocks_at_cycle0() -> None:
    judge = _FakeJudge("CONTRADICTED")
    report = await audit(
        draft_text="A norma estabelece normas gerais [C1].",
        chunks=[CHUNK],
        template=DEFAULT_TEMPLATE,
        judge=judge,
        repair_cycle=0,
    )
    assert report.decision == Decision.BLOCKED
    assert report.repair_cycle == 0


@pytest.mark.asyncio
async def test_blocking_finding_blocks() -> None:
    judge = _FakeJudge("SUPPORTED")
    report = await audit(
        draft_text="Art. 42 veda a prática [C1].",
        chunks=[{"chunk_id": "c1", "text": "Art. 30 veda a prática.", "kind": "dispositivo"}],
        template=DEFAULT_TEMPLATE,
        judge=judge,
        repair_cycle=0,
    )
    assert report.decision == Decision.BLOCKED


@pytest.mark.asyncio
async def test_clean_draft_passes() -> None:
    judge = _FakeJudge("SUPPORTED")
    draft = (
        "## Escopo\n- A norma estabelece normas gerais [C1].\n"
        "## Análise\n- A medida impacta o setor [C1].\n"
        "## Recomendação\n- Observar os prazos legais [C1]."
    )
    report = await audit(
        draft_text=draft,
        chunks=[
            {"chunk_id": "c1", "text": "A norma estabelece normas gerais.", "kind": "dispositivo"}
        ],
        template=DEFAULT_TEMPLATE,
        judge=judge,
        repair_cycle=0,
    )
    assert report.decision == Decision.PASS
    assert judge.calls == 3  # três frases citadas julgadas


@pytest.mark.asyncio
async def test_budget_overflow_blocks_with_explicit_reason() -> None:
    judge = _FakeJudge("SUPPORTED")
    budget = BudgetState(max_cost_usd=0.0, deadline_s=10**9)
    budget.add_cost(0.01)
    report = await audit(
        draft_text="A norma estabelece normas [C1].",
        chunks=[CHUNK],
        template=DEFAULT_TEMPLATE,
        judge=judge,
        repair_cycle=0,
        budget=budget,
    )
    assert report.decision == Decision.BLOCKED
    assert any("orçamento" in fix for fix in report.needed_fixes)


# ── Laço de reparo (via run_pipeline, gerador e juiz falsos) ──────────────────


class _LoopGenerator:
    """Gerador falso: distingue triage/draft pelo prompt e conta drafts."""

    def __init__(self, markdown: str, span: str) -> None:
        self._markdown = markdown
        self._span = span
        self.draft_calls = 0

    async def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        thinking: str | None = None,
    ) -> Generation:
        used = model or "deepseek-flash"
        if "Classifique" in prompt:
            return Generation(
                content=json.dumps({"relevante": True, "justificativa": "ia", "temas": ["ia"]}),
                model=used,
                usage=Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=0),
            )
        self.draft_calls += 1
        return Generation(
            content=json.dumps(
                {
                    "markdown": self._markdown,
                    "evidence_spans": [{"citation": 1, "span": self._span}],
                }
            ),
            model=used,
            usage=Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=0),
        )


DRAFT_MD = "A norma estabelece prazo de 90 dias [C1]."
SPAN = "A norma prevê adaptação em 90 dias."

# Chunk/span para o caso BLOCKING: fonte só alcança Art. 30, draft cita Art. 42.
BLOCKING_CHUNK = {"chunk_id": "c1", "text": "Art. 30 veda a prática.", "kind": "dispositivo"}


async def _load_document(doc_id: str) -> dict[str, Any]:
    return {"ementa": "PL sobre inteligência artificial", "keywords": "ia, governança"}


async def _load_chunks(doc_id: str) -> list[dict[str, str]]:
    return [CHUNK]


async def _load_blocking_chunks(doc_id: str) -> list[dict[str, str]]:
    return [BLOCKING_CHUNK]


def _settings() -> Settings:
    return Settings(DEEPSEEK_API_KEY="test")


@pytest.mark.asyncio
async def test_always_failing_blocks_at_cycle2_after_two_repairs(tmp_path: Any) -> None:
    gen = _LoopGenerator(DRAFT_MD, SPAN)
    judge = _FakeJudge("UNSUPPORTED", needed_fix="Citar o trecho que define o prazo.")
    outcome = await run_pipeline(
        doc_id="d1",
        generator=gen,
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )
    assert outcome.partial is False
    assert outcome.report.audit is not None
    assert outcome.report.audit.decision == Decision.BLOCKED
    assert outcome.report.audit.repair_cycle == 2
    assert gen.draft_calls == 3  # 1 inicial + exatamente 2 reparos


@pytest.mark.asyncio
async def test_contradicted_blocks_without_any_repair(tmp_path: Any) -> None:
    gen = _LoopGenerator(DRAFT_MD, SPAN)
    judge = _FakeJudge("CONTRADICTED")
    outcome = await run_pipeline(
        doc_id="d1",
        generator=gen,
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )
    assert outcome.report.audit is not None
    assert outcome.report.audit.decision == Decision.BLOCKED
    assert outcome.report.audit.repair_cycle == 0
    assert gen.draft_calls == 1  # nenhum reparo


@pytest.mark.asyncio
async def test_blocking_blocks_without_any_repair(tmp_path: Any) -> None:
    gen = _LoopGenerator("Art. 42 veda a prática [C1].", "Art. 30 veda a prática.")
    judge = _FakeJudge("SUPPORTED")
    outcome = await run_pipeline(
        doc_id="d1",
        generator=gen,
        load_document=_load_document,
        load_chunks=_load_blocking_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )
    assert outcome.report.audit is not None
    assert outcome.report.audit.decision == Decision.BLOCKED
    assert gen.draft_calls == 1  # BLOCKING nunca repara
