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

from rig.core.citations import (
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
    revision_notes: Sequence[str] = (),
) -> str:
    restricoes = "\n".join(f"- {r}" for r in (positioning.restricoes if positioning else []))
    fontes = "\n".join(
        f"[C{i}] {chunk_id(c)} — {chunk_text(c)}" for i, c in enumerate(chunks, start=1)
    )
    notas = "\n".join(f"- {n}" for n in revision_notes)
    return (
        "Redija uma minuta técnica em Markdown sobre a proposição, usando títulos "
        "de seção e, sob cada título, uma lista de afirmações.\n\n"
        "REGRAS DE CITAÇÃO — validação MECÂNICA, sem exceção:\n"
        "- Cada frase de conteúdo (que fala sobre o projeto) DEVE terminar com "
        "[C<n>], onde n é o índice (1-based) da fonte em FONTES que a sustenta.\n"
        "- Uma frase exige citação quando contém número, prazo, data, percentual "
        "ou valor, OU quando tem verbo de efeito/obrigação (estabelece, determina, "
        "dispõe, define, cria, altera, modifica, revoga, aplica, veda, proíbe, "
        "permite, exige, obriga, prevê, institui, assegura, garante).\n"
        '- Atenção: frases como "A Lei não se aplica a X" ou "A Lei prevê Y" têm '
        "verbo factual e TAMBÉM exigem [C<n>].\n"
        "- Títulos de seção (linhas começando com #) não precisam de citação.\n"
        "- Não escreva parágrafo introdutório sem citação: se descreve o projeto, "
        "cite a fonte.\n\n"
        "Exemplo VÁLIDO:\n"
        "## Escopo\n"
        "- A Lei estabelece normas gerais de governança de IA [C2].\n\n"
        "Exemplo INVÁLIDO (a minuta inteira será rejeitada):\n"
        "- A Lei não se aplica a uso particular. (sem [C<n>])\n\n"
        f"Proposição: {proposition}\n"
        f"Restrições (não afirmar):\n{restricoes or '(nenhuma)'}\n\n"
        f"FONTES:\n{fontes}\n\n"
        + (
            f"Correções obrigatórias da revisão anterior (aplique TODAS):\n{notas}\n\n"
            if notas
            else ""
        )
        + "Responda APENAS com um objeto JSON com exatamente estes campos:\n"
        '{"markdown": <string com a minuta em Markdown>, '
        '"evidence_spans": [{"citation": <n>, "span": <string>}, ...]}\n\n'
        'Para cada citação [C<n>] usada, inclua um item em "evidence_spans" com o '
        'mesmo n e, em "span", um trecho COPIADO VERBATIM (substring literal) do '
        "texto da fonte [Cn] em FONTES, com ao menos 20 caracteres. Não parafraseie "
        "o span: copie exatamente, inclusive acentuação e pontuação."
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
    revision_notes: Sequence[str] = (),
) -> DraftResult:
    if generator is None:
        raise DraftError("draft exige um gerador (LLM mockado nos testes)")
    prompt = _build_draft_prompt(positioning, chunks, proposition, revision_notes)
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
    revision_notes: Sequence[str] = (),
) -> Any:
    """Entrada pública do nó ``draft`` (síncrona ou assíncrona)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _draft_impl(
                positioning,
                chunks,
                generator=generator,
                proposition=proposition,
                revision_notes=revision_notes,
            )
        )
    return _draft_impl(
        positioning,
        chunks,
        generator=generator,
        proposition=proposition,
        revision_notes=revision_notes,
    )


__all__ = ["DraftError", "DraftResult", "draft"]
