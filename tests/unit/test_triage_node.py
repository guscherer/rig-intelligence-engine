from __future__ import annotations

import pytest
from pydantic import ValidationError

from rig.graph.nodes.triage import TriageResult, triage


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
