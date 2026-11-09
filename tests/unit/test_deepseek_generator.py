"""Testes do adapter DeepSeek — sem rede (httpx.MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from rig.adapters import DeepSeekGenerator, GenerationError, Usage
from rig.adapters.deepseek import _parse_usage


def _transport_handler(
    *,
    status: int = 200,
    content: str = "",
    usage: dict | None = None,
    model: str = "deepseek-flash",
) -> httpx.MockTransport:
    body = {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage or {},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, request=request)

    return httpx.MockTransport(handler)


def test_parse_usage_extracts_reasoning_from_details() -> None:
    usage = _parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 79,
            "completion_tokens_details": {"reasoning_tokens": 63},
        }
    )
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 79
    assert usage.reasoning_tokens == 63


def test_parse_usage_reasoning_fallback_top_level() -> None:
    usage = _parse_usage({"prompt_tokens": 5, "completion_tokens": 3, "reasoning_tokens": 2})
    assert usage.reasoning_tokens == 2


@pytest.mark.asyncio
async def test_generate_returns_generation_with_real_usage() -> None:
    gen = DeepSeekGenerator(
        api_key="k",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        transport=_transport_handler(
            content="ok",
            usage={
                "prompt_tokens": 38,
                "completion_tokens": 10,
                "completion_tokens_details": {"reasoning_tokens": 10},
            },
        ),
    )
    generation = await gen.generate("oi")
    assert generation.content == "ok"
    assert generation.model == "deepseek-flash"
    assert generation.usage.prompt_tokens == 38
    assert generation.usage.completion_tokens == 10
    assert generation.usage.reasoning_tokens == 10
    assert gen.total_usage.prompt_tokens == 38


@pytest.mark.asyncio
async def test_generate_non_200_raises_generation_error() -> None:
    gen = DeepSeekGenerator(
        api_key="k",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(402, text="insufficient balance", request=request)
        ),
    )
    with pytest.raises(GenerationError):
        await gen.generate("oi")


def test_usage_accumulates() -> None:
    a = Usage(prompt_tokens=1, completion_tokens=2, reasoning_tokens=3)
    b = Usage(prompt_tokens=10, completion_tokens=20, reasoning_tokens=30)
    total = a + b
    assert total.prompt_tokens == 11
    assert total.completion_tokens == 22
    assert total.reasoning_tokens == 33
