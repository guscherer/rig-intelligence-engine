"""Tipos compartilhados pelas três camadas da auditoria (docs/03-agents.md §6).

As três camadas — regras determinísticas (§6.1), NLI (§6.2) e checagem global
(§6.3) — produzem o mesmo tipo: :class:`Finding`. Um tipo só, definido aqui e
importado nos outros módulos; reexportar em outro caminho é card falho.

``extra="forbid"`` no :class:`Finding` é intencional: um campo novo que apareça
sem ser declarado aqui é erro de contrato, não silêncio — as camadas não podem
começar a produzir campos divergentes sem quebrar o gate.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RuleCode(StrEnum):
    """Código estável de cada regra determinística (camada 1 e checagem global §6.3)."""

    ORPHAN_CITATION = "orphan_citation"  # [C9] com índice inexistente
    MISSING_ARTICLE = "missing_article"  # "Art. 42" quando a fonte só vai até Art. 30
    NUMBER_MISMATCH = "number_mismatch"  # número/data divergente entre afirmação e fonte
    UNCITED_FACT = "uncited_fact"  # frase factual sem [C
    FORBIDDEN_LANGUAGE = "forbidden_language"  # "inconstitucional", "certamente", "garantimos"
    PREAMBLE_AS_DEVICE = "preamble_as_device"  # cita preâmbulo como se fosse dispositivo
    UNCITED_QUANTITY = "uncited_quantity"  # %/R$/mil/milhão/bilhão em frase sem [C
    UNSUPPORTED_PROMISE = "unsupported_promise"  # prazo/resultado prometido ausente da fonte
    MISSING_SECTION = "missing_section"  # seção obrigatória do template ausente
    EMPTY_SECTION = "empty_section"  # seção presente mas vazia/placeholder


class Severity(StrEnum):
    """Severidade do finding. A política de saída (F3.4) decide o desfecho por aqui."""

    BLOCKING = "blocking"  # erro factual objetivo: nunca repara sozinho (§6.4)
    REPAIRABLE = "repairable"  # pode voltar ao draft


class Finding(BaseModel):
    """Um problema encontrado pela auditoria, com contexto suficiente para o reparo."""

    model_config = ConfigDict(extra="forbid")

    code: RuleCode
    sentence: str
    detail: str
    chunk_id: str | None
    severity: Severity


class Usage(BaseModel):
    """Tokens consumidos em uma chamada do juiz NLI (contabilidade local da auditoria).

    Tipo local para a fronteira de pacote (docs/10 §1: ``rig.audit`` só importa
    ``rig.core``): o juiz acumula uso e custo sem depender do tipo do provedor —
    o gerador concreto é injetado pelo runner.
    """

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
