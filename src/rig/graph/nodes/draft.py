"""Nó ``draft`` — gera seções Markdown com citação obrigatória (docs/03 §5).

Toda frase factual carrega ``[C<n>]`` apontando para ``chunks[n-1]``, e cada
``evidence_span`` é validado como substring literal do texto do chunk. A
validação é feita pelo portão local (``rig.graph.citations``) antes de devolver
o resultado; violação é erro, nunca silêncio.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig.graph.citations import (
    CitationSpan,
    chunk_id,
    chunk_text,
    normalize_evidence_spans,
    validate_draft,
)
from rig.graph.nodes.positioning import PositioningBrief


class DraftResult(BaseModel):
    """Resultado tipado do nó ``draft``."""

    model_config = ConfigDict(extra="forbid")

    markdown: str = ""
    evidence_spans: list[CitationSpan] = Field(default_factory=list)


class DraftError(Exception):
    """Falha na redação (gerador ausente ou saída ilegível)."""


async def _call_generator(generator: Any, prompt: str) -> Any:
    result = generator(prompt)
    if inspect.isawaitable(result):
        result = await result
    return result


def _build_draft_prompt(
    positioning: PositioningBrief | None,
    chunks: Sequence[Any],
    proposition: str,
) -> str:
    restricoes = "\n".join(f"- {r}" for r in (positioning.restricoes if positioning else []))
    fontes = "\n".join(
        f"[C{i}] {chunk_id(c)} — {chunk_text(c)}" for i, c in enumerate(chunks, start=1)
    )
    return (
        "Redija a minuta em Markdown. Cada frase que afirma fato, número, prazo "
        "ou obrigação termina com [C<n>], onde n indexa FONTES.\n"
        f"Proposição: {proposition}\n"
        f"Restrições (não afirmar):\n{restricoes or '(nenhuma)'}\n\n"
        f"FONTES:\n{fontes}"
    )


def _parse_draft_output(raw: Any) -> tuple[str, list[CitationSpan]]:
    if isinstance(raw, str):
        return raw, []
    if isinstance(raw, DraftResult):
        return raw.markdown, raw.evidence_spans
    if isinstance(raw, dict):
        markdown = (
            raw.get("markdown") or raw.get("draft") or raw.get("text") or raw.get("content") or ""
        )
        if isinstance(markdown, dict):
            markdown = "\n\n".join(str(v) for v in markdown.values())
        spans = normalize_evidence_spans(raw.get("evidence_spans") or [])
        return str(markdown), spans
    raise DraftError(f"saída do gerador ilegível: {raw!r}")


async def _draft_impl(
    positioning: PositioningBrief | None,
    chunks: Sequence[Any],
    *,
    generator: Any,
    proposition: str,
) -> DraftResult:
    if generator is None:
        raise DraftError("draft exige um gerador (LLM mockado nos testes)")
    prompt = _build_draft_prompt(positioning, chunks, proposition)
    raw = await _call_generator(generator, prompt)
    markdown, spans = _parse_draft_output(raw)
    validate_draft(markdown, chunks, spans)
    return DraftResult(markdown=markdown, evidence_spans=spans)


def draft(
    positioning: PositioningBrief | None = None,
    chunks: Sequence[Any] = (),
    *,
    generator: Any = None,
    proposition: str = "",
) -> Any:
    """Entrada pública do nó ``draft`` (síncrona ou assíncrona)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _draft_impl(positioning, chunks, generator=generator, proposition=proposition)
        )
    return _draft_impl(positioning, chunks, generator=generator, proposition=proposition)


__all__ = ["DraftError", "DraftResult", "draft"]
