"""E2E do portão de auditoria (docs/07 F3) — LLM e juiz mockados, grafo real.

Cobre o laço de reparo ``draft → audit`` na aresta real do runner:
um draft que nasce ``UNSUPPORTED`` e repara no ciclo 1; um que nunca repara e
bloqueia no ciclo 2 com as frases listadas; um ``CONTRADICTED`` que bloqueia
sem reparo. Em todos os caminhos o ``emit`` recebe ``AuditReport`` (nenhuma
minuta sai sem relatório), e o relatório carrega a taxa de ``UNSUPPORTED``
antes/depois do reparo — o critério de pronto do F3.

Sem rede, sem LLM real, sem custo. Texto sintético (ADR-009).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rig.adapters import Generation, Usage
from rig.audit import Decision, SentenceVerdict, Verdict
from rig.core.config import Settings
from rig.graph.runner import run_pipeline

CHUNK = {
    "chunk_id": "c1",
    "text": "A norma define diretrizes gerais para o setor.",
    "kind": "dispositivo",
}

# Minuta limpa com as três seções obrigatórias do template padrão — o único
# defeito do run é o veredito do juiz, controlado por caso.
CLEAN_DRAFT = (
    "## Escopo\n"
    "A norma define diretrizes gerais para o setor [C1].\n"
    "## Análise\n"
    "A medida altera os procedimentos administrativos [C1].\n"
    "## Recomendação\n"
    "Observar as diretrizes estabelecidas [C1]."
)
SPAN = "A norma define diretrizes gerais para o setor"


class _FixedJudge:
    """Juiz NLI falso que devolve sempre o mesmo veredito e conta chamadas."""

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


class _RepairOnceJudge:
    """UNSUPPORTED só na primeira frase (ciclo 0); SUPPORTED daí em diante.

    O gerador devolve a mesma minuta a cada reparo, então a "correção" é
    representada pela mudança de veredito do juiz: ciclo 0 repara, ciclo 1 passa.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def judge(self, sentence: str, span: str, citation: int) -> SentenceVerdict:
        self.calls += 1
        unsupported = self.calls == 1
        return SentenceVerdict(
            sentence=sentence,
            citation=citation,
            verdict=Verdict.UNSUPPORTED if unsupported else Verdict.SUPPORTED,
            justification="mock",
            needed_fix="Citar o trecho que define o prazo." if unsupported else None,
        )


class _Generator:
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


async def _load_document(doc_id: str) -> dict[str, Any]:
    return {"ementa": "PL sobre inteligência artificial", "keywords": "ia, governança"}


async def _load_chunks(doc_id: str) -> list[dict[str, str]]:
    return [CHUNK]


def _settings() -> Settings:
    return Settings(DEEPSEEK_API_KEY="test")


def _run(judge: Any, tmp_path: Path) -> Any:
    return run_pipeline(
        doc_id="d1",
        generator=_Generator(CLEAN_DRAFT, SPAN),
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )


@pytest.mark.asyncio
async def test_unsupported_repairs_once_then_passes(tmp_path: Path) -> None:
    """Nasce UNSUPPORTED, repara no ciclo 1 e emite PASS (1 reparo, taxa cai)."""

    gen = _Generator(CLEAN_DRAFT, SPAN)
    judge = _RepairOnceJudge()
    outcome = await run_pipeline(
        doc_id="d1",
        generator=gen,
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )
    report = outcome.report.audit
    assert report is not None
    assert report.decision == Decision.PASS
    assert report.repair_cycle == 1
    assert gen.draft_calls == 2  # 1 inicial + exatamente 1 reparo
    # Taxa de UNSUPPORTED antes/depois (critério de pronto do F3).
    assert report.unsupported_rate_before == pytest.approx(1 / 3)
    assert report.unsupported_rate_after == 0.0
    assert report.unsupported_rate_before > report.unsupported_rate_after


@pytest.mark.asyncio
async def test_never_repairs_blocks_at_cycle2_with_phrases(tmp_path: Path) -> None:
    """Nunca repara → BLOCKED no ciclo 2, com as frases no relatório."""

    gen = _Generator(CLEAN_DRAFT, SPAN)
    judge = _FixedJudge("UNSUPPORTED", needed_fix="Citar o trecho que define o prazo.")
    outcome = await run_pipeline(
        doc_id="d1",
        generator=gen,
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )
    report = outcome.report.audit
    assert report is not None
    assert report.decision == Decision.BLOCKED
    # O bloqueio tem que sobreviver no status de topo do run.json (§6.4).
    assert outcome.report.status == "blocked"
    assert report.repair_cycle == 2
    assert gen.draft_calls == 3  # 1 inicial + 2 reparos, então bloqueia
    # As frases UNSUPPORTED estão listadas no relatório.
    unsupported = [v.sentence for v in report.verdicts if v.verdict == Verdict.UNSUPPORTED]
    assert len(unsupported) == 3
    assert any("diretrizes gerais" in s for s in unsupported)
    assert any("Citar o trecho" in fix for fix in report.needed_fixes)
    # Nunca melhorou: a taxa antes == depois.
    assert report.unsupported_rate_before == 1.0
    assert report.unsupported_rate_after == 1.0


@pytest.mark.asyncio
async def test_contradicted_blocks_without_any_repair(tmp_path: Path) -> None:
    """CONTRADICTED bloqueia imediato, sem gastar reparo."""

    gen = _Generator(CLEAN_DRAFT, SPAN)
    judge = _FixedJudge("CONTRADICTED")
    outcome = await run_pipeline(
        doc_id="d1",
        generator=gen,
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
        judge=judge,
    )
    report = outcome.report.audit
    assert report is not None
    assert report.decision == Decision.BLOCKED
    assert outcome.report.status == "blocked"
    assert report.repair_cycle == 0
    assert gen.draft_calls == 1  # nenhum reparo


@pytest.mark.asyncio
async def test_emit_receives_audit_report_on_every_path(tmp_path: Path) -> None:
    """O run.json emitido carrega AuditReport em todos os caminhos (PASS/BLOCKED)."""

    cases: list[Any] = [
        _RepairOnceJudge(),  # repara → PASS
        _FixedJudge("UNSUPPORTED", needed_fix="Citar o trecho que define o prazo."),  # BLOCKED
        _FixedJudge("CONTRADICTED"),  # BLOCKED
    ]
    for judge in cases:
        outcome = await _run(judge, tmp_path)
        assert outcome.report.audit is not None
        # A minuta emitida em disco tem o relatório serializado ao lado.
        run_dir = tmp_path / outcome.report.run_id
        data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert data["audit"] is not None
        assert data["audit"]["decision"] in {"PASS", "BLOCKED"}
        # O status de topo do run.json acompanha o veredito da auditoria:
        # BLOCKED vira "blocked", PASS vira "ok".
        expected_status = "blocked" if data["audit"]["decision"] == "BLOCKED" else "ok"
        assert data["status"] == expected_status
        assert outcome.report.status == expected_status
        assert "unsupported_rate_before" in data["audit"]
        assert "unsupported_rate_after" in data["audit"]
