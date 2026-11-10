"""Testes do juiz NLI por sentença (docs/03 §6.2) — sem rede.

O ``StructuredGenerator`` é mockado e **captura** o payload de cada chamada:
é assim que se comprova ``temperature=0`` e ``model=deepseek-flash`` sem gastar
um token. Todo texto é sintético (ADR-009).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from rig.adapters import Generation, Usage
from rig.audit import DeepSeekNliJudge, NliJudgeError, SentenceVerdict, Verdict
from rig.audit.nli import MAX_JUSTIFICATION_CHARS

SENTENCE = "A norma estabelece prazo de 90 dias."
SPAN = "Art. 5º A norma estabelece prazo de 90 dias para adaptação."


def _ok_json(verdict: str, *, justification: str = "ok", needed_fix: Any = None) -> str:
    return json.dumps(
        {"verdict": verdict, "justification": justification, "needed_fix": needed_fix}
    )


class _FakeGenerator:
    """Mock de ``StructuredGenerator`` que captura kwargs e devolve ``Generation``."""

    def __init__(self, content: str, *, model: str = "deepseek-flash") -> None:
        self._content = content
        self._model = model
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "prompt": prompt,
                "json_mode": json_mode,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "system": system,
                "model": model,
                "effort": effort,
                "thinking": thinking,
            }
        )
        return Generation(
            content=self._content,
            model=model or self._model,
            usage=Usage(prompt_tokens=42, completion_tokens=17, reasoning_tokens=9),
        )


def _judge(verdict: str, *, justification: str = "ok", needed_fix: Any = None) -> DeepSeekNliJudge:
    content = json.dumps(
        {"verdict": verdict, "justification": justification, "needed_fix": needed_fix}
    )
    return DeepSeekNliJudge(_FakeGenerator(content))


def _judge_with_raw(raw: str) -> DeepSeekNliJudge:
    return DeepSeekNliJudge(_FakeGenerator(raw))


# ── Vereditos válidos ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_supported_passes_through_unchanged() -> None:
    judge = _judge("SUPPORTED")
    result = await judge.judge(SENTENCE, SPAN, 1)
    assert result.verdict == Verdict.SUPPORTED
    assert result.sentence == SENTENCE
    assert result.citation == 1
    assert result.needed_fix is None


@pytest.mark.asyncio
async def test_partial_is_a_valid_verdict() -> None:
    judge = _judge("PARTIAL", justification="trata do tema, mas não do específico")
    result = await judge.judge(SENTENCE, SPAN, 1)
    assert result.verdict == Verdict.PARTIAL


@pytest.mark.asyncio
async def test_unsupported_carries_needed_fix_when_model_provided() -> None:
    judge = _judge("UNSUPPORTED", needed_fix="Citar o trecho que define o prazo, não o genérico.")
    result = await judge.judge(SENTENCE, SPAN, 1)
    assert result.verdict == Verdict.UNSUPPORTED
    assert result.needed_fix == "Citar o trecho que define o prazo, não o genérico."


# ── Falha fechada (nunca vira SUPPORTED) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_verdict_outside_enum_raises() -> None:
    judge = _judge("TALVEZ")
    with pytest.raises(NliJudgeError):
        await judge.judge(SENTENCE, SPAN, 1)


@pytest.mark.asyncio
async def test_missing_verdict_raises() -> None:
    judge = _judge_with_raw(json.dumps({"justification": "sem veredito", "needed_fix": None}))
    with pytest.raises(NliJudgeError):
        await judge.judge(SENTENCE, SPAN, 1)


@pytest.mark.asyncio
async def test_malformed_json_raises() -> None:
    judge = _judge_with_raw('não é json {{{ "verdict":')
    with pytest.raises(NliJudgeError):
        await judge.judge(SENTENCE, SPAN, 1)


# ── Justificativa limitada a 200 chars ───────────────────────────────────────


@pytest.mark.asyncio
async def test_justification_truncated_to_200_chars_with_warning() -> None:
    judge = _judge("SUPPORTED", justification="x" * 250)
    with pytest.warns(UserWarning):
        result = await judge.judge(SENTENCE, SPAN, 1)
    assert len(result.justification) == MAX_JUSTIFICATION_CHARS


@pytest.mark.asyncio
async def test_justification_within_limit_kept_intact() -> None:
    short = "o trecho implica a afirmação"
    judge = _judge("SUPPORTED", justification=short)
    result = await judge.judge(SENTENCE, SPAN, 1)
    assert result.justification == short


# ── Contrato da chamada (temperature=0 e modelo deepseek-flash) ──────────────


@pytest.mark.asyncio
async def test_payload_has_temperature_zero_and_deepseek_flash() -> None:
    fake = _FakeGenerator(_ok_json("SUPPORTED"))
    judge = DeepSeekNliJudge(fake)
    await judge.judge(SENTENCE, SPAN, 1)
    call = fake.calls[0]
    assert call["temperature"] == 0.0
    assert call["model"] == "deepseek-flash"
    assert call["json_mode"] is True


@pytest.mark.asyncio
async def test_payload_limits_reasoning_for_classification() -> None:
    """NLI é classificação (§9): raciocínio desligado e teto dimensionado."""
    fake = _FakeGenerator(_ok_json("SUPPORTED"))
    judge = DeepSeekNliJudge(fake)
    await judge.judge(SENTENCE, SPAN, 1)
    call = fake.calls[0]
    assert call["thinking"] == "disabled"
    assert call["effort"] == "low"
    assert call["max_tokens"] == 512


@pytest.mark.asyncio
async def test_prompt_uses_delimiters_and_no_external_knowledge() -> None:
    fake = _FakeGenerator(_ok_json("SUPPORTED"))
    judge = DeepSeekNliJudge(fake)
    await judge.judge(SENTENCE, SPAN, 1)
    prompt = fake.calls[0]["prompt"]
    assert f"<trecho>{SPAN}</trecho>" in prompt
    assert f"<afirmacao>{SENTENCE}</afirmacao>" in prompt
    assert "Não use conhecimento externo" in prompt


# ── Contrato do tipo ─────────────────────────────────────────────────────────


def test_sentence_verdict_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SentenceVerdict(
            sentence=SENTENCE,
            citation=1,
            verdict=Verdict.SUPPORTED,
            justification="ok",
            needed_fix=None,
            campo_inventado="não deveria existir",
        )
