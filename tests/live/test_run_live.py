"""Teste live do provedor real (fora do gate normal — ``-m live``).

Roda **uma** consulta ao DeepSeek e confere o que o requisito de auditoria
exige: HTTP 200 (implícito no sucesso), ``usage`` presente e custo > 0.
O custo do run completo é medido rodando ``make run --id 2487262``, não aqui.
"""

from __future__ import annotations

import pytest

from rig.adapters import DeepSeekGenerator
from rig.core.config import get_settings


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_generation_has_usage_and_positive_cost() -> None:
    settings = get_settings()
    generator = DeepSeekGenerator(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.model_draft,
    )
    try:
        generation = await generator.generate(
            "Responda apenas com a palavra OK.",
            json_mode=False,
            temperature=0.0,
            max_tokens=16,
        )
    finally:
        await generator.aclose()

    # HTTP 200 é garantido por GenerationError ser levantada em não-2xx.
    assert generation.usage.prompt_tokens > 0
    assert generation.usage.completion_tokens > 0
    cost = (
        generation.usage.prompt_tokens * settings.input_cost_per_token
        + generation.usage.completion_tokens * settings.output_cost_per_token
    )
    assert cost > 0
