"""Adapter do provedor DeepSeek (OpenAI-compatible) — única porta de rede de geração.

ADR-012: o SDK do provedor vive só em ``rig/adapters/``; os nós do grafo
dependem do protocolo ``StructuredGenerator`` (DIP, docs/10 §4), não deste
adapter concreto. Este módulo usa ``httpx`` direto (sem SDK de terceiro) para
chamar ``POST /chat/completions``.

Custos (docs/03 §7 e ADR-012): o provedor cobra ``prompt_tokens`` e
``completion_tokens``; os tokens de raciocínio vêm em
``completion_tokens_details.reasoning_tokens`` e **já estão contidos** em
``completion_tokens`` (uma resposta de 179 tokens totais consumiu 63 de
reasoning — custo real ~2,7 vezes o texto visível). Este adapter apenas **reporta**
os três contadores; a precificação fica em ``rig.core.config`` e é aplicada pelo
``BudgetState``.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict


class Usage(BaseModel):
    """Tokens consumidos em uma chamada (prompt, completion, reasoning)."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


class Generation(BaseModel):
    """Saída de uma geração: conteúdo + modelo + uso (para contabilizar custo)."""

    model_config = ConfigDict(extra="forbid")

    content: str
    model: str
    usage: Usage


class GenerationError(Exception):
    """Falha de rede/provedor na borda do sistema (HTTP não-2xx, corpo ilegível)."""


class StructuredGenerator(Protocol):
    """Protocolo estreito de geração (docs/10 §4): o nó recebe isto, não o SDK."""

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
    ) -> Generation: ...


def _parse_usage(raw: Any) -> Usage:
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raw = {}
    details = raw.get("completion_tokens_details")
    reasoning = 0
    if isinstance(details, dict):
        reasoning = int(details.get("reasoning_tokens") or 0)
    if reasoning == 0:
        reasoning = int(raw.get("reasoning_tokens") or 0)
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
        reasoning_tokens=reasoning,
    )


class DeepSeekGenerator:
    """Gera texto via DeepSeek e reporta o ``Usage`` real de cada chamada."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )
        self._total = Usage()

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
        """Chama ``/chat/completions`` e devolve ``Generation`` com ``Usage`` real.

        Em ``json_mode``, força ``response_format=json_object`` e pede JSON ao
        modelo via system prompt (DeepSeek exige o termo "json" no prompt).
        ``model`` sobrescreve o modelo padrão da instância (config por nó, ADR-012);
        ``effort`` (``low``/``high``/``max``) limita o raciocínio via
        ``reasoning_effort``; ``thinking`` (``enabled``/``disabled``) liga/desliga
        o modo de raciocínio (chain-of-thought) — ``disabled`` zera os
        ``reasoning_tokens`` e devolve só o ``content``.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        elif json_mode:
            messages.append(
                {
                    "role": "system",
                    "content": "Responda exclusivamente com um objeto JSON válido, "
                    "sem texto antes ou depois e sem cercas de código.",
                }
            )
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if effort is not None:
            payload["reasoning_effort"] = effort
        if thinking is not None:
            payload["thinking"] = {"type": thinking}

        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise GenerationError(f"falha de rede no provedor: {exc}") from exc

        if response.status_code != 200:
            raise GenerationError(
                f"provedor respondeu HTTP {response.status_code}: {response.text[:400]}"
            )

        try:
            data = response.json()
            choice = data["choices"][0]
            content = (choice.get("message") or {}).get("content") or ""
            usage = _parse_usage(data.get("usage"))
            model_used = str(data.get("model") or self.model)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationError(f"resposta do provedor ilegível: {exc}") from exc

        generation = Generation(content=str(content), model=model_used, usage=usage)
        self._total = self._total + usage
        return generation

    async def __call__(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Generation:
        return await self.generate(
            prompt,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @property
    def total_usage(self) -> Usage:
        return self._total

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = [
    "DeepSeekGenerator",
    "Generation",
    "GenerationError",
    "StructuredGenerator",
    "Usage",
    "_parse_usage",
]
