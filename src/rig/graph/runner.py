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

import inspect
import json
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rig.adapters import Generation, StructuredGenerator
from rig.audit import AuditReport, Decision, DeepSeekNliJudge, NliJudge, SectionTemplate
from rig.core.config import Settings, get_settings
from rig.graph.citations import CitationError, CitationSpan
from rig.graph.nodes.audit import DEFAULT_TEMPLATE, audit
from rig.graph.nodes.draft import DraftResult, draft
from rig.graph.nodes.positioning import positioning
from rig.graph.nodes.retrieve import retrieve
from rig.graph.nodes.triage import triage
from rig.graph.state import BudgetExceededError, BudgetState, RIGState
from rig.graph.state import RetrievedChunk as StateRetrievedChunk

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
    audit: AuditReport | None = None


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


class _BudgetedGenerator:
    """Envolve o ``StructuredGenerator`` para contabilizar cada chamada no ``BudgetState``.

    O juiz NLI (``DeepSeekNliJudge``) espera um ``StructuredGenerator``; este
    adapter preserva a interface e, a cada ``generate``, registra o ``Usage``
    real no orçamento (mesma contabilidade de :func:`_node_generator`), para que
    estouro no meio da auditoria seja detectado chamada a chamada.
    """

    def __init__(
        self,
        generator: StructuredGenerator,
        budget: BudgetState,
        settings: Settings,
    ) -> None:
        self._generator = generator
        self._budget = budget
        self._settings = settings

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
    ) -> Generation:
        generation = await self._generator.generate(
            prompt,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
            model=model,
            effort=effort,
        )
        self._budget.record_usage(
            generation.usage.model_dump(),
            input_cost_per_token=self._settings.input_cost_per_token,
            output_cost_per_token=self._settings.output_cost_per_token,
        )
        return generation


def _to_state_chunks(items: list[Any]) -> list[StateRetrievedChunk]:
    out: list[StateRetrievedChunk] = []
    for item in items or []:
        if isinstance(item, StateRetrievedChunk):
            out.append(item)
            continue
        if isinstance(item, dict):
            out.append(
                StateRetrievedChunk(
                    chunk_id=str(item.get("chunk_id", item.get("id", ""))),
                    doc_id=item.get("doc_id"),
                    score=item.get("score"),
                    breadcrumb=item.get("breadcrumb"),
                    text=item.get("text", item.get("chunk_text")),
                    kind=item.get("kind"),
                )
            )
            continue
        out.append(
            StateRetrievedChunk(
                chunk_id=str(getattr(item, "chunk_id", getattr(item, "id", item))),
                doc_id=getattr(item, "doc_id", None),
                score=getattr(item, "score", None),
                breadcrumb=getattr(item, "breadcrumb", None),
                text=getattr(item, "text", getattr(item, "chunk_text", None)),
                kind=getattr(item, "kind", None),
            )
        )
    return out


async def _await_if_needed(value: Any) -> Any:
    """Aguarda o valor se for awaitable; caso contrário, devolve-o direto.

    Permite que nós (ou mocks de teste) sejam síncronos ou assíncronos sem
    que o runner precise conhecer a forma de chamada.
    """
    if inspect.isawaitable(value):
        return await value
    return value


async def _draft_with_repair(
    *,
    generator: StructuredGenerator,
    budget: BudgetState,
    modelos: dict[str, str],
    settings: Settings,
    chunks: list[Any],
    ementa: str,
    position_brief: Any,
    revision_notes: Sequence[str] = (),
) -> DraftResult:
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
    notes = list(revision_notes)
    draft_result: DraftResult | None = None
    for attempt in range(2):
        try:
            draft_result = await draft(
                positioning=position_brief,
                chunks=chunks,
                generator=draft_gen,
                proposition=ementa,
                revision_notes=notes,
            )
            break
        except CitationError as exc:
            if attempt == 0:
                notes = [str(exc)]
                continue
            raise
    if draft_result is None:
        raise RuntimeError("draft não produziu resultado")
    return draft_result


async def _audit_and_repair(
    *,
    draft_result: DraftResult,
    chunks: list[Any],
    template: SectionTemplate,
    judge: NliJudge,
    state: RIGState,
    generator: StructuredGenerator,
    modelos: dict[str, str],
    settings: Settings,
) -> tuple[DraftResult, AuditReport]:
    """Aresta ``draft -> audit`` (docs/03 §6.4): repara até 2 ciclos e então emite.

    Devolve o ``DraftResult`` final e o relatório da última auditoria. A política
    (:func:`rig.audit.policy.decide`) devolve ``BLOCKED`` no ciclo 2, então o
    laço termina por construção.
    """
    while True:
        report = await audit(
            draft_text=draft_result.markdown,
            chunks=chunks,
            template=template,
            judge=judge,
            repair_cycle=state.repair_cycle,
            budget=state.budget,
        )
        state.audit = report
        if report.decision is not Decision.REPAIR or state.repair_cycle >= 2:
            return draft_result, report
        state.repair_cycle += 1
        state.revision_notes = list(report.needed_fixes)
        state.budget.check()
        draft_result = await _draft_with_repair(
            generator=generator,
            budget=state.budget,
            modelos=modelos,
            settings=settings,
            chunks=chunks,
            ementa=state.proposition or "",
            position_brief=state.position,
            revision_notes=state.revision_notes,
        )
        state.draft = draft_result.markdown
        state.budget.check()


async def _run_relevant_path(
    *,
    ementa: str,
    doc_id: str,
    load_chunks: ChunkLoader,
    generator: StructuredGenerator,
    budget: BudgetState,
    modelos: dict[str, str],
    settings: Settings,
    state: RIGState,
) -> tuple[list[Any], DraftResult]:
    retrieved = await _await_if_needed(
        retrieve(
            query=ementa,
            filters={"doc_id": doc_id},
            doc_id=doc_id,
            search=lambda q, filters=None: load_chunks(doc_id),  # noqa: ARG005
        )
    )
    retrieved_list = list(retrieved) if retrieved is not None else []
    state.retrieved = _to_state_chunks(retrieved_list)

    chunks = retrieved_list if retrieved_list else await load_chunks(doc_id)
    if not chunks:
        raise RuntimeError(f"documento {doc_id!r} não possui chunks no corpus")

    # Chunks institucionais (kind="institucional"), quando existirem no
    # conjunto recuperado; caso contrário, o nó sinaliza insuficiente.
    institutional_chunks = [
        c
        for c in retrieved_list
        if (c.get("kind") if isinstance(c, dict) else getattr(c, "kind", None)) == "institucional"
    ]
    position_brief = await _await_if_needed(
        positioning(corpus=institutional_chunks if institutional_chunks else None)
    )
    state.position = position_brief

    budget.check()
    draft_result = await _draft_with_repair(
        generator=generator,
        budget=budget,
        modelos=modelos,
        settings=settings,
        chunks=chunks,
        ementa=ementa,
        position_brief=position_brief,
    )
    state.draft = draft_result.markdown
    budget.check()
    return chunks, draft_result


async def run_pipeline(
    *,
    doc_id: str,
    generator: StructuredGenerator,
    load_document: DocumentLoader,
    load_chunks: ChunkLoader,
    settings: Settings | None = None,
    reports_dir: Path = Path("reports"),
    judge: NliJudge | None = None,
    audit_template: SectionTemplate | None = None,
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
    nli_judge: NliJudge = judge or DeepSeekNliJudge(_BudgetedGenerator(generator, budget, settings))
    template = audit_template or DEFAULT_TEMPLATE
    started = time.monotonic()

    markdown = ""
    partial_reason: str | None = None
    evidence_spans: list[CitationSpan] = []
    audit_report: AuditReport | None = None

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
        triage_result = await triage(ementa=ementa, keywords=keywords, generator=triage_gen)
        budget.check()

        # Estado tipado do grafo (RIGState): instanciado e preenchido para auditoria.
        state = RIGState(run_id=run_id, doc_id=doc_id, budget=budget, proposition=ementa)
        state.triage = triage_result

        if not getattr(triage_result, "relevante", True):
            # Triage decidiu que a proposição não é relevante: curto-circuito,
            # sem recuperar nem redigir (evita inventar em cima de base fraca).
            state.status = "partial"
            state.error = "skipped (insufficient_base): triage relevante=False"
            partial_reason = state.error
        else:
            _chunks, draft_result = await _run_relevant_path(
                ementa=ementa,
                doc_id=doc_id,
                load_chunks=load_chunks,
                generator=generator,
                budget=budget,
                modelos=modelos,
                settings=settings,
                state=state,
            )
            draft_result, audit_report = await _audit_and_repair(
                draft_result=draft_result,
                chunks=_chunks,
                template=template,
                judge=nli_judge,
                state=state,
                generator=generator,
                modelos=modelos,
                settings=settings,
            )
            markdown = draft_result.markdown
            evidence_spans = draft_result.evidence_spans

        if partial_reason is None:
            state.status = "ok"
        state.cost_usd = budget.spent_usd
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
        audit=audit_report,
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
