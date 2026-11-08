"""Nó ``positioning`` — não é RAG, é restrição (docs/03 §4).

O nó define o que a minuta **não** pode dizer: limites da casa e escopo
institucional. A saída entra no prompt do ``draft`` como restrição, não como
texto recuperado. Sem corpus institucional que sustente, sinaliza
``insuficiente=True`` em vez de inventar restrições.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig.graph.citations import chunk_id, chunk_text


class PositioningBrief(BaseModel):
    """Resultado tipado do nó ``positioning`` (docs/03 §4)."""

    model_config = ConfigDict(extra="forbid")

    restricoes: list[str] = Field(default_factory=list)
    escopo: str = ""
    fonte_restricoes: list[str] = Field(default_factory=list)
    insuficiente: bool = False


async def _call_generator(generator: Any, prompt: str) -> Any:
    result = generator(prompt)
    if inspect.isawaitable(result):
        result = await result
    return result


def _positioning_prompt(chunks: Sequence[Any], red_lines: Sequence[str]) -> str:
    linhas = "\n".join(f"- {r}" for r in red_lines) if red_lines else "(nenhuma)"
    fontes = "\n".join(f"- {chunk_id(c)}: {chunk_text(c)}" for c in chunks)
    return (
        "Extraia as restrições institucionais (o que a minuta NÃO pode afirmar) "
        "do corpus abaixo. Responda com restricoes (lista), escopo (string) e "
        "fonte_restricoes (lista, uma fonte por restrição).\n"
        f"Linhas vermelhas conhecidas:\n{linhas}\n\nCorpus:\n{fontes}"
    )


def _to_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, BaseModel):
        return raw.model_dump()
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        return {"escopo": raw} if raw.strip() else {}
    return {}


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value]


def _parse_positioning(raw: Any, *, escopo: str) -> PositioningBrief | None:
    data = _to_dict(raw)
    if not data:
        return None
    restricoes = _str_list(data.get("restricoes") or data.get("restrictions"))
    fontes = _str_list(data.get("fonte_restricoes") or data.get("fontes"))
    escopo_out = data.get("escopo") or escopo
    return PositioningBrief(
        restricoes=restricoes,
        escopo=str(escopo_out),
        fonte_restricoes=fontes,
        insuficiente=False,
    )


async def _positioning_impl(
    corpus: Sequence[Any] | None,
    *,
    red_lines: Sequence[str],
    generator: Any,
    escopo: str,
) -> PositioningBrief:
    chunks = [c for c in (corpus or []) if chunk_text(c).strip()]
    if not chunks:
        return PositioningBrief(insuficiente=True)

    if generator is not None:
        raw = await _call_generator(generator, _positioning_prompt(chunks, red_lines))
        brief = _parse_positioning(raw, escopo=escopo)
        if brief is not None:
            return brief

    # Fallback determinístico: o corpus institucional É a restrição.
    restricoes: list[str] = []
    fontes: list[str] = []
    for i, red_line in enumerate(red_lines):
        restricoes.append(f"A minuta não deve se posicionar sobre: {red_line}.")
        fontes.append(f"config:linhas_vermelhas:{i}")
    for chunk in chunks:
        restricoes.append(chunk_text(chunk).strip())
        fontes.append(chunk_id(chunk))
    return PositioningBrief(
        restricoes=restricoes,
        escopo=escopo,
        fonte_restricoes=fontes,
        insuficiente=False,
    )


def positioning(
    corpus: Sequence[Any] | None = None,
    *,
    red_lines: Sequence[str] = (),
    generator: Any = None,
    escopo: str = "",
) -> Any:
    """Entrada pública do nó ``positioning`` (síncrona ou assíncrona)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _positioning_impl(corpus, red_lines=red_lines, generator=generator, escopo=escopo)
        )
    return _positioning_impl(corpus, red_lines=red_lines, generator=generator, escopo=escopo)


__all__ = ["PositioningBrief", "positioning"]
