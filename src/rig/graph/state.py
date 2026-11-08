from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BudgetExceededError(Exception):
    def __init__(
        self,
        limit: str,
        spent: float,
        limit_value: float,
        over_by: float,
    ) -> None:
        self.limit = limit
        self.spent = spent
        self.limit_value = limit_value
        self.over_by = over_by
        super().__init__(
            f"budget exceeded ({limit}): spent={spent:.6f}, "
            f"limit={limit_value:.6f}, over_by={over_by:.6f}"
        )


def _to_epoch(value: Any) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return float(value.timestamp())
    return float(value)


def _usage_get(usage: Any, *names: str) -> Any:
    if isinstance(usage, dict):
        for name in names:
            if name in usage:
                return usage[name]
        return None
    for name in names:
        if hasattr(usage, name):
            return getattr(usage, name)
    return None


def _nested_get(usage: Any, *path: str) -> Any:
    cur = usage
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key) if key in cur else None
        else:
            cur = getattr(cur, key, None) if cur is not None else None
        if cur is None:
            return None
    return cur


class BudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spent_usd: float = 0.0
    started_at: datetime | float = Field(default_factory=lambda: datetime.now(UTC))
    max_cost_usd: float = 0.20
    deadline_s: float = 90.0
    # Contadores de tokens (prompt vs. completion), com reasoning separado.
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    def check(self, now: Any = None) -> None:
        current = time.time() if now is None else _to_epoch(now)
        started = _to_epoch(self.started_at)
        elapsed = current - started
        if elapsed > self.deadline_s:
            raise BudgetExceededError(
                "deadline",
                self.spent_usd,
                self.deadline_s,
                elapsed - self.deadline_s,
            )
        if self.spent_usd > self.max_cost_usd:
            raise BudgetExceededError(
                "cost",
                self.spent_usd,
                self.max_cost_usd,
                self.spent_usd - self.max_cost_usd,
            )

    def add_cost(self, amount: float) -> None:
        self.spent_usd += float(amount)

    def record_usage(  # noqa: C901,PLR0912  # resolves heterogeneous usage shapes and pricing kwargs
        self,
        usage: Any,
        input_cost_per_token: float | None = None,
        output_cost_per_token: float | None = None,
        **kwargs: Any,
    ) -> float:
        prompt = _usage_get(usage, "prompt_tokens", "promptTokenCount", "input_tokens")
        completion = _usage_get(usage, "completion_tokens", "candidatesTokenCount", "output_tokens")
        reasoning = _nested_get(usage, "completion_tokens_details", "reasoning_tokens")
        if reasoning is None:
            reasoning = _usage_get(usage, "reasoning_tokens")
        prompt = int(prompt or 0)
        completion = int(completion or 0)
        reasoning = int(reasoning or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.reasoning_tokens += reasoning
        in_rate = input_cost_per_token
        out_rate = output_cost_per_token
        prices = kwargs.pop("prices", None)
        if isinstance(prices, dict):
            if in_rate is None:
                for k in ("input", "prompt", "input_cost_per_token", "prompt_cost_per_token"):
                    if k in prices:
                        in_rate = float(prices[k])
                        break
            if out_rate is None:
                for k in (
                    "output",
                    "completion",
                    "output_cost_per_token",
                    "completion_cost_per_token",
                ):
                    if k in prices:
                        out_rate = float(prices[k])
                        break
        if "cost_per_token" in kwargs:
            v = kwargs.pop("cost_per_token")
            if in_rate is None:
                in_rate = float(v)
            if out_rate is None:
                out_rate = float(v)
        if in_rate is None:
            in_rate = 1e-6
        if out_rate is None:
            out_rate = in_rate
        cost = prompt * float(in_rate) + completion * float(out_rate)
        self.spent_usd += cost
        return cost


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk_id: str
    doc_id: str | None = None
    score: float | None = None
    breadcrumb: str | None = None
    text: str | None = None
    kind: str | None = None


class RIGState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    doc_id: str
    budget: BudgetState
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    sections: dict[str, str] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    status: str = "pending"
    error: str | None = None
    # Campos do fluxo (opcionais, preenchidos pelos nós).
    proposition: str | None = None
    mandate: str | None = None
    triage: Any | None = None
    position: str | None = None
    draft: str | None = None
    audit: str | None = None
    repair_cycle: int = 0
    revision_notes: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


def cost_from_usage(usage: Any, *a: Any, **kw: Any) -> float:
    b = BudgetState()
    return b.record_usage(usage, *a, **kw)


def tokens_from_usage(usage: Any) -> tuple[int, int, int]:
    prompt = int(_usage_get(usage, "prompt_tokens", "promptTokenCount", "input_tokens") or 0)
    completion = int(
        _usage_get(usage, "completion_tokens", "candidatesTokenCount", "output_tokens") or 0
    )
    reasoning = _nested_get(usage, "completion_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = _usage_get(usage, "reasoning_tokens")
    return prompt, completion, int(reasoning or 0)
