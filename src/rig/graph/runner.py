"""Runner do grafo RIG: ``triage -> retrieve -> positioning -> draft -> emit``.

Este módulo é a composição raiz (docs/10 §4): recebe um ``StructuredGenerator``
(protocolo) e carregadores de documento/chunks, orquestra os nós, contabiliza o
custo real no ``BudgetState`` e emite a minuta + ``run.json`` em disco.

Regras de orçamento (docs/03 §7, docs/01 §5):

* o ``BudgetState`` é checado **antes** de cada nó (deadline/custo) e **após**
  cada chamada de LLM (custo recém-contabilizado);
* estouro não mata o run: desvia para ``emit_partial``, gravando o que já
  existir **marcado como parcial** no arquivo e no ``run.json``.

O custo deriva dos tokens reportados pelo provedor (``prompt``/``completion``,
com ``reasoning`` registrado à parte — ADR-012) multiplicados pelos preços da
config; nunca é um número inventado.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rig.adapters import Generation, StructuredGenerator
from rig.core.config import Settings, get_settings
from rig.graph.citations import CitationError, CitationSpan
from rig.graph.nodes.draft import DraftResult, draft
from rig.graph.nodes.positioning import positioning
from rig.graph.nodes.triage import triage
from rig.graph.state import BudgetExceededError, BudgetState

DocumentLoader = Callable[[str], Awaitable[dict[str, Any] | None]]
ChunkLoader = Callable[[str], Awaitable[list[Any]]]

DRAFT_TEMPERATURE = 0.3
# deepseek-flash opera em modo "thinking" por padrão: gasta tokens de raciocínio
# ANTES de emitir o conteúdo (ADR-012). Um teto apertado deixa a resposta sem
# corpo; este valor acomoda o raciocínio + a minuta + os evidence_spans.
DRAFT_MAX_TOKENS = 20000
TRIAGE_MAX_TOKENS = 2048


@dataclass(frozen=True)
class _NodeLLM:
    """Configuração de LLM de um nó (modelo, modo JSON, temperatura, teto)."""

    model: str
    json_mode: bool
    temperature: float
    max_tokens: int
    effort: str | None = None


class TokenCounts(BaseModel):
    """Contadores de tokens do run (keys fixas do contrato de auditoria)."""

    model_config = ConfigDict(extra="forbid")

    prompt: int = 0
    completion: int = 0
    reasoning: int = 0


class BudgetInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float
    deadline_s: float


class RunReport(BaseModel):
    """Conteúdo de ``reports/<run_id>/run.json`` (evidência de custo)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    doc_id: str
    cost_usd: float
    tokens: TokenCounts
    budget: BudgetInfo
    duration_s: float
    modelos: dict[str, str]
    status: Literal["ok", "partial"]
    partial_reason: str | None = None
    pricing: dict[str, float]
    evidence_spans: list[CitationSpan] = Field(default_factory=list)


@dataclass
class RunOutcome:
    """Resultado completo do run (para testes e CLI)."""

    report: RunReport
    markdown: str
    partial: bool


def _node_generator(
    generator: StructuredGenerator,
    budget: BudgetState,
    modelos: dict[str, str],
    node: str,
    settings: Settings,
    llm: _NodeLLM,
) -> Callable[[str], Awaitable[Any]]:
    """Adapta o ``StructuredGenerator`` ao contrato dos nós (``gen(prompt)``).

    Cada chamada contabiliza o ``Usage`` real no ``BudgetState`` e registra o
    modelo usado pelo nó. Retorna o conteúdo já parseado quando ``json_mode``.
    """

    async def call(prompt: str) -> Any:
        generation: Generation = await generator.generate(
            prompt,
            json_mode=llm.json_mode,
            temperature=llm.temperature,
            max_tokens=llm.max_tokens,
            model=llm.model,
            effort=llm.effort,
        )
        budget.record_usage(
            generation.usage.model_dump(),
            input_cost_per_token=settings.input_cost_per_token,
            output_cost_per_token=settings.output_cost_per_token,
        )
        modelos[node] = generation.model
        if llm.json_mode:
            return json.loads(generation.content)
        return generation.content

    return call


async def run_pipeline(
    *,
    doc_id: str,
    generator: StructuredGenerator,
    load_document: DocumentLoader,
    load_chunks: ChunkLoader,
    settings: Settings | None = None,
    reports_dir: Path = Path("reports"),
) -> RunOutcome:
    """Executa o grafo e emite ``minuta.md`` + ``run.json`` em ``reports/<run_id>/``.

    ``load_document`` devolve o ``doc_meta`` (ementa/keywords) e ``load_chunks``
    devolve os chunks do documento — ambos injetados para testabilidade; a CLI
    liga-os ao Postgres real.
    """
    settings = settings or get_settings()
    run_id = f"run-{doc_id}-{uuid.uuid4().hex[:8]}"
    budget = BudgetState(
        max_cost_usd=settings.max_cost_usd_per_run,
        deadline_s=settings.max_deadline_s,
    )
    modelos: dict[str, str] = {}
    started = time.monotonic()

    markdown = ""
    partial_reason: str | None = None
    evidence_spans: list[CitationSpan] = []

    chunks: list[Any] = []

    try:
        meta = await load_document(doc_id)
        if meta is None:
            raise RuntimeError(f"documento {doc_id!r} não encontrado no corpus")
        ementa = str(meta.get("ementa") or "")
        keywords = meta.get("keywords")

        budget.check()
        triage_gen = _node_generator(
            generator,
            budget,
            modelos,
            "triage",
            settings,
            _NodeLLM(
                model=settings.model_triage,
                json_mode=True,
                temperature=0.0,
                max_tokens=TRIAGE_MAX_TOKENS,
            ),
        )
        await triage(ementa=ementa, keywords=keywords, generator=triage_gen)
        budget.check()

        chunks = await load_chunks(doc_id)
        if not chunks:
            raise RuntimeError(f"documento {doc_id!r} não possui chunks no corpus")

        # positioning: sem corpus institucional, é honesto sinalizar insuficiente
        # (docs/03 §4). Não há chamada de LLM — não gera custo.
        await positioning(corpus=None)

        budget.check()
        draft_gen = _node_generator(
            generator,
            budget,
            modelos,
            "draft",
            settings,
            _NodeLLM(
                model=settings.model_draft,
                json_mode=True,
                temperature=DRAFT_TEMPERATURE,
                max_tokens=DRAFT_MAX_TOKENS,
                effort="low",
            ),
        )
        # Portão local (docs/03 §5): rejeita minuta sem citação. Uma única
        # tentativa de reparo com o erro exato antes de desistir.
        revision_notes: list[str] = []
        draft_result: DraftResult | None = None
        for attempt in range(2):
            try:
                draft_result = await draft(
                    chunks=chunks,
                    generator=draft_gen,
                    proposition=ementa,
                    revision_notes=revision_notes,
                )
                break
            except CitationError as exc:
                if attempt == 0:
                    revision_notes = [str(exc)]
                    continue
                raise
        if draft_result is not None:
            markdown = draft_result.markdown
            evidence_spans = draft_result.evidence_spans
        budget.check()
    except BudgetExceededError as exc:
        partial_reason = str(exc)
    except Exception as exc:  # borda do run: qualquer falha vira partial, nunca derruba
        partial_reason = f"{type(exc).__name__}: {exc}"

    duration = time.monotonic() - started
    partial = partial_reason is not None
    report = RunReport(
        run_id=run_id,
        doc_id=doc_id,
        cost_usd=round(budget.spent_usd, 8),
        tokens=TokenCounts(
            prompt=budget.prompt_tokens,
            completion=budget.completion_tokens,
            reasoning=budget.reasoning_tokens,
        ),
        budget=BudgetInfo(max_cost_usd=budget.max_cost_usd, deadline_s=budget.deadline_s),
        duration_s=round(duration, 3),
        modelos=modelos,
        status="partial" if partial else "ok",
        partial_reason=partial_reason,
        pricing={
            "input_cost_per_token": settings.input_cost_per_token,
            "output_cost_per_token": settings.output_cost_per_token,
        },
        evidence_spans=evidence_spans,
    )
    _write_reports(reports_dir, run_id, markdown, report, partial)
    return RunOutcome(report=report, markdown=markdown, partial=partial)


def _write_reports(
    reports_dir: Path,
    run_id: str,
    markdown: str,
    report: RunReport,
    partial: bool,
) -> None:
    out_dir = reports_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if partial:
        header = (
            "<!-- MINUTA PARCIAL — execução interrompida antes de concluir "
            "todas as etapas (orçamento/falha). -->\n\n"
            "# MINUTA PARCIAL\n\n"
            "_Este documento foi emitido como parcial e NÃO deve ser tratado "
            "como minuta final._\n\n"
        )
        body = markdown if markdown.strip() else "Nenhuma minuta foi produzida antes do estouro.\n"
        (out_dir / "minuta.md").write_text(header + body, encoding="utf-8")
    else:
        (out_dir / "minuta.md").write_text(markdown, encoding="utf-8")

    (out_dir / "run.json").write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "BudgetInfo",
    "RunOutcome",
    "RunReport",
    "TokenCounts",
    "run_pipeline",
]
