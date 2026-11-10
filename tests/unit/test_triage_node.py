from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rig.adapters import Generation, GenerationError, Usage
from rig.core.config import Settings
from rig.graph.nodes.triage import TriageError, TriageResult, triage
from rig.graph.runner import run_pipeline


@pytest.mark.asyncio
async def test_triage_typed_and_score_deterministic() -> None:
    def gen(prompt: str) -> dict:
        return {
            "relevante": True,
            "temas": ["tributario"],
            "justificativa": "x",
            "magnitude": 4,
            "urgency": 3,
            "confidence": 0.9,
        }

    r1 = await triage(ementa="PL", generator=gen)

    def gen2(prompt: str) -> dict:
        return {**gen(prompt), "justificativa": "outra redacao"}

    r2 = await triage(ementa="PL", generator=gen2)
    assert isinstance(r1, TriageResult)
    assert r1.score == r2.score
    assert 0.0 <= r1.score <= 1.0


def test_triage_rejects_invalid_score() -> None:
    with pytest.raises(ValidationError):
        TriageResult(relevante=True, score=1.5, justificativa="x", temas=[])


@pytest.mark.asyncio
async def test_triage_propagates_async_generator_failure() -> None:
    async def gen(prompt: str) -> dict:
        raise GenerationError("provedor indisponivel")

    with pytest.raises(GenerationError, match="provedor indisponivel"):
        await triage(ementa="PL", generator=gen)


@pytest.mark.asyncio
async def test_triage_propagates_sync_callable_failure() -> None:
    def gen(prompt: str) -> dict:
        raise RuntimeError("falha sincrona")

    with pytest.raises(RuntimeError, match="falha sincrona"):
        await triage(ementa="PL", generator=gen)


def test_triage_sync_entry_propagates_callable_failure() -> None:
    def gen(prompt: str) -> dict:
        raise ValueError("falha sync entry")

    with pytest.raises(ValueError, match="falha sync entry"):
        triage(ementa="PL", generator=gen)


@pytest.mark.asyncio
async def test_triage_non_json_string_response_raises_triage_error() -> None:
    def gen(prompt: str) -> str:
        return "isto nao e json"

    with pytest.raises(TriageError):
        await triage(ementa="PL", generator=gen)


@pytest.mark.asyncio
async def test_triage_non_json_generation_raises_triage_error() -> None:
    def gen(prompt: str) -> Generation:
        return Generation(content="nao e json", model="m", usage=Usage())

    with pytest.raises(TriageError):
        await triage(ementa="PL", generator=gen)


@pytest.mark.asyncio
async def test_run_pipeline_triage_failure_is_partial(tmp_path: Path) -> None:
    class FailingGenerator:
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
            raise GenerationError("provedor indisponivel")

    async def load_document(doc_id: str) -> dict[str, object] | None:
        return {"ementa": "PL sobre inteligencia artificial", "keywords": "ia"}

    async def load_chunks(doc_id: str) -> list[dict[str, str]]:
        return [{"chunk_id": "c1", "text": "trecho"}]

    def settings() -> Settings:
        return Settings(DEEPSEEK_API_KEY="test")

    outcome = await run_pipeline(
        doc_id="d1",
        generator=FailingGenerator(),
        load_document=load_document,
        load_chunks=load_chunks,
        settings=settings(),
        reports_dir=tmp_path,
    )

    assert outcome.partial is True
    assert outcome.report.status == "partial"
    assert outcome.report.status != "ok"
    assert "provedor indisponivel" in (outcome.report.partial_reason or "")
