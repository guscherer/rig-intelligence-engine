"""Testes do runner ponta a ponta (gerador/loaders falsos, sem rede nem banco)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig.adapters import Generation, Usage
from rig.core.config import Settings
from rig.graph import runner
from rig.graph.nodes.positioning import PositioningBrief
from rig.graph.runner import run_pipeline

CHUNKS = [
    {"chunk_id": "c1", "text": "O projeto altera a alíquota do ICMS de 18% para 15%."},
    {"chunk_id": "c2", "text": "A proposta estabelece prazo de 90 dias para adequação."},
    {"chunk_id": "c3", "text": "O texto revoga o artigo 42 da lei anterior."},
]

DRAFT_MD = (
    "## Escopo\n"
    "O projeto altera a alíquota do ICMS de 18% para 15% [C1].\n"
    "## Análise\n"
    "A proposta estabelece prazo de 90 dias para adequação [C2].\n"
    "## Recomendação\n"
    "Observar o prazo de 90 dias para adequação [C2]."
)
SPANS = [
    {"citation": 1, "span": "altera a alíquota do ICMS de 18% para 15%"},
    {"citation": 2, "span": "prazo de 90 dias para adequação"},
]


class FakeGenerator:
    """Gerador fake: distingue triage/draft pelo prompt e devolve Usage controlável."""

    def __init__(self, *, draft_completion_tokens: int = 100) -> None:
        self._draft_completion = draft_completion_tokens

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
                content=json.dumps(
                    {"relevante": True, "justificativa": "tema de IA", "temas": ["ia"]}
                ),
                model=used,
                usage=Usage(prompt_tokens=100, completion_tokens=20, reasoning_tokens=5),
            )
        if "Avalie se o TRECHO sustenta" in prompt:
            return Generation(
                content=json.dumps(
                    {"verdict": "SUPPORTED", "justification": "ok", "needed_fix": None}
                ),
                model=used,
                usage=Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=0),
            )
        return Generation(
            content=json.dumps({"markdown": DRAFT_MD, "evidence_spans": SPANS}),
            model=used,
            usage=Usage(
                prompt_tokens=500,
                completion_tokens=self._draft_completion,
                reasoning_tokens=100,
            ),
        )


async def _load_document(doc_id: str) -> dict[str, object]:
    return {"ementa": "PL sobre inteligência artificial", "keywords": "ia, governança"}


async def _load_chunks(doc_id: str) -> list[dict[str, str]]:
    return CHUNKS


def _settings() -> Settings:
    return Settings(DEEPSEEK_API_KEY="test")


@pytest.mark.asyncio
async def test_run_pipeline_emits_minuta_and_run_json(tmp_path: Path) -> None:
    outcome = await run_pipeline(
        doc_id="d1",
        generator=FakeGenerator(),
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
    )
    assert outcome.partial is False
    report = outcome.report
    assert report.status == "ok"
    assert report.cost_usd > 0
    assert report.tokens.prompt > 0
    assert report.tokens.completion > 0
    assert report.tokens.reasoning > 0
    assert report.modelos == {"triage": "deepseek-flash", "draft": "deepseek-flash"}

    run_dir = tmp_path / report.run_id
    assert (run_dir / "minuta.md").exists()
    assert (run_dir / "run.json").exists()

    md = (run_dir / "minuta.md").read_text(encoding="utf-8")
    assert "[C1]" in md and "[C2]" in md
    assert "PARCIAL" not in md

    data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert data["run_id"] == report.run_id
    assert data["doc_id"] == "d1"
    assert data["status"] == "ok"
    assert set(data["tokens"]) == {"prompt", "completion", "reasoning"}
    assert set(data["budget"]) == {"max_cost_usd", "deadline_s"}
    # aritmética do custo fecha com os tokens (requisito de auditoria do F2.5)
    in_rate = data["pricing"]["input_cost_per_token"]
    out_rate = data["pricing"]["output_cost_per_token"]
    expected = data["tokens"]["prompt"] * in_rate + data["tokens"]["completion"] * out_rate
    assert data["cost_usd"] == pytest.approx(expected, abs=1e-9)


@pytest.mark.asyncio
async def test_run_pipeline_budget_overflow_emits_partial(tmp_path: Path) -> None:
    outcome = await run_pipeline(
        doc_id="d1",
        generator=FakeGenerator(draft_completion_tokens=1_000_000),
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
    )
    assert outcome.partial is True
    assert outcome.report.status == "partial"
    assert outcome.report.partial_reason is not None

    run_dir = tmp_path / outcome.report.run_id
    md = (run_dir / "minuta.md").read_text(encoding="utf-8")
    assert "PARCIAL" in md
    data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert data["status"] == "partial"


@pytest.mark.asyncio
async def test_run_pipeline_missing_document_is_partial(tmp_path: Path) -> None:
    async def missing(doc_id: str) -> dict[str, object] | None:
        return None

    outcome = await run_pipeline(
        doc_id="nope",
        generator=FakeGenerator(),
        load_document=missing,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
    )
    assert outcome.partial is True
    assert outcome.report.status == "partial"
    assert "não encontrado" in (outcome.report.partial_reason or "")


@pytest.mark.asyncio
async def test_run_pipeline_repairs_uncited_draft(tmp_path: Path) -> None:
    """Primeiro draft sem citação é rejeitado; o reparo (1 tentativa) corrige."""

    class RepairGenerator:
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
                    content=json.dumps(
                        {"relevante": True, "justificativa": "tema de IA", "temas": ["ia"]}
                    ),
                    model=used,
                    usage=Usage(prompt_tokens=100, completion_tokens=20, reasoning_tokens=5),
                )
            if "Avalie se o TRECHO sustenta" in prompt:
                return Generation(
                    content=json.dumps(
                        {"verdict": "SUPPORTED", "justification": "ok", "needed_fix": None}
                    ),
                    model=used,
                    usage=Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=0),
                )
            if "Correções" in prompt:
                content = json.dumps({"markdown": DRAFT_MD, "evidence_spans": SPANS})
            else:
                content = json.dumps(
                    {"markdown": "O projeto altera a alíquota do ICMS.", "evidence_spans": []}
                )
            return Generation(
                content=content,
                model=used,
                usage=Usage(prompt_tokens=500, completion_tokens=100, reasoning_tokens=50),
            )

    outcome = await run_pipeline(
        doc_id="d1",
        generator=RepairGenerator(),
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
    )
    assert outcome.partial is False
    assert outcome.report.status == "ok"
    assert "[C1]" in outcome.markdown


@pytest.mark.asyncio
async def test_run_pipeline_wires_positioning_into_draft_prompt_and_retrieve_doc_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aceite F2.6: saída de positioning chega ao prompt do draft e retrieve
    é chamado com doc_id."""
    captured: dict[str, object] = {"retrieve_kwargs": None, "prompts": []}

    async def fake_retrieve(*args: object, **kwargs: object) -> list[object]:
        captured["retrieve_kwargs"] = dict(kwargs)
        return []

    async def fake_positioning(*args: object, **kwargs: object) -> PositioningBrief:
        return PositioningBrief(restricoes=["RESTRICAO_SECRETA_X"])

    class CapturingGenerator(FakeGenerator):
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
            prompts = captured["prompts"]
            assert isinstance(prompts, list)
            prompts.append(prompt)
            return await super().generate(
                prompt,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
                system=system,
                model=model,
                effort=effort,
                thinking=thinking,
            )

    monkeypatch.setattr(runner, "retrieve", fake_retrieve)
    monkeypatch.setattr(runner, "positioning", fake_positioning)

    outcome = await run_pipeline(
        doc_id="d1",
        generator=CapturingGenerator(),
        load_document=_load_document,
        load_chunks=_load_chunks,
        settings=_settings(),
        reports_dir=tmp_path,
    )

    assert outcome.partial is False
    retrieve_kwargs = captured["retrieve_kwargs"]
    assert isinstance(retrieve_kwargs, dict)
    assert retrieve_kwargs.get("doc_id") == "d1" or (
        isinstance(retrieve_kwargs.get("filters"), dict)
        and retrieve_kwargs["filters"].get("doc_id") == "d1"
    )
    prompts = captured["prompts"]
    assert isinstance(prompts, list)
    assert any("RESTRICAO_SECRETA_X" in str(p) for p in prompts)
