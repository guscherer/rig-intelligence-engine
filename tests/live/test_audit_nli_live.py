"""Teste live do juiz NLI real (fora do gate — ``-m live``).

Roda **uma** chamada ao DeepSeek e confere o que o requisito de auditoria
exige: veredito dentro do enum e contabilidade (``usage`` e custo) presente.
Sem ``usage``/custo não há como precificar a camada (docs/03 §7).
"""

from __future__ import annotations

import pytest

from rig.adapters import DeepSeekGenerator
from rig.audit import DeepSeekNliJudge, Verdict
from rig.core.config import get_settings

SENTENCE = "A norma estabelece prazo de 90 dias para adaptação."
SPAN = "Art. 5º As empresas terão 90 dias, contados da publicação, para se adaptar."


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_nli_judge_verdict_and_accounting() -> None:
    settings = get_settings()
    generator = DeepSeekGenerator(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.model_audit,
    )
    judge = DeepSeekNliJudge(
        generator,
        model=settings.model_audit,
        input_cost_per_token=settings.input_cost_per_token,
        output_cost_per_token=settings.output_cost_per_token,
    )
    try:
        result = await judge.judge(sentence=SENTENCE, span=SPAN, citation=1)
    finally:
        await generator.aclose()

    assert result.verdict in {
        Verdict.SUPPORTED,
        Verdict.PARTIAL,
        Verdict.UNSUPPORTED,
        Verdict.CONTRADICTED,
    }
    assert result.justification
    # Sem usage/custo não há contabilidade (docs/03 §7).
    assert judge.total_usage.prompt_tokens > 0
    assert judge.total_usage.completion_tokens > 0
    assert judge.total_cost_usd > 0
