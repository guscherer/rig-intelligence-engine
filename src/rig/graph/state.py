"""Estado tipado do grafo RIG e orçamento de execução.

`RIGState` é o único objeto que atravessa o grafo (docs/01 §3). `BudgetState`
carrega o teto de custo e deadline por run (docs/03 §7): ``max_cost_usd=0.20``
e ``deadline_s=90``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BudgetExceededError(Exception):
    """Estouro de orçamento (custo ou deadline).

    Attributes:
        limit: qual limite estourou (``"cost"`` ou ``"deadline"``).
        spent: valor gasto/medido no momento do estouro.
        limit_value: teto configurado.
        over_by: quanto passou do teto.
    """

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
    """Contabilidade de custo e prazo de um run.

    Teto por run (docs/03 §7): ``max_cost_usd=0.20``, ``deadline_s=90``.
    """

    model_config = ConfigDict(extra="allow")

    spent_usd: float = 0.0
    started_at: datetime | float = Field(default_factory=lambda: datetime.now(UTC))
    max_cost_usd: float = 0.20
    deadline_s: float = 90.0

    # Contadores de tokens (prompt vs. completion), com reasoning separado.
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    def _started_epoch(self) -> float:
        return _to_epoch(self.started_at)

    def check(self, now: Any = None) -> None:
        """Levanta ``BudgetExceeded`` se custo ou deadline estouraram."""
        current = time.time() if now is None else _to_epoch(now)
        started = self._started_epoch()
        elapsed = current - started
        if elapsed > self.deadline_s:
            raise BudgetExceeded(
                "deadline",
                self.spent_usd,
                self.deadline_s,
                elapsed - self.deadline_s,
            )
        if self.spent_usd > self.max_cost_usd:
            raise BudgetExceeded(
                "cost",
                self.spent_usd,
                self.max_cost_usd,
                self.spent_usd - self.max_cost_usd,
            )

    # Aliases de verificação (compatibilidade com callers/testes).
    def check_budget(self, now: Any = None) -> None:
        self.check(now)

    def ensure_within_budget(self, now: Any = None) -> None:
        self.check(now)

    def enforce(self, now: Any = None) -> None:
        self.check(now)

    def raise_if_exceeded(self, now: Any = None) -> None:
        self.check(now)

    def validate(self, now: Any = None) -> None:  # type: ignore[override]
        self.check(now)

    def ensure_budget(self, now: Any = None) -> None:
        self.check(now)

    def check_limits(self, now: Any = None) -> None:
        self.check(now)

    def assert_within_budget(self, now: Any = None) -> None:
        self.check(now)

    def add_cost(self, amount: float) -> None:
        self.spent_usd += float(amount)

    # Aliases de custo.
    def charge(self, amount: float) -> None:
        self.add_cost(amount)

    def record_cost(self, amount: float) -> None:
        self.add_cost(amount)

    def add_spent(self, amount: float) -> None:
        self.add_cost(amount)

    def spent_add(self, amount: float) -> None:
        self.add_cost(amount)

    def add(self, amount: float) -> None:  # pragma: no cover - alias
        self.add_cost(amount)

    def charge_cost(self, amount: float) -> None:
        self.add_cost(amount)

    def _rates_from_kwargs(self, kwargs: dict[str, Any]) -> tuple[float, float]:  # noqa: C901
        in_rate: float | None = None
        out_rate: float | None = None
        for key, val in kwargs.items():
            lk = key.lower()
            if val is None:
                continue
            if "cost_per_token" in lk or lk == "cost_per_token":
                if in_rate is None:
                    in_rate = float(val)
                if out_rate is None:
                    out_rate = float(val)
                continue
            if any(t in lk for t in ("input", "prompt", "in")) and "token" in lk:
                in_rate = float(val)
                continue
            if any(t in lk for t in ("output", "completion", "out")) and "token" in lk:
                out_rate = float(val)
                continue
            if lk in (
                "input_price",
                "prompt_price",
                "price_input",
                "price_prompt",
                "input_rate",
                "prompt_rate",
            ):
                in_rate = float(val)
                continue
            if lk in (
                "output_price",
                "completion_price",
                "price_output",
                "price_completion",
                "output_rate",
                "completion_rate",
            ):
                out_rate = float(val)
                continue
        if in_rate is None:
            in_rate = 1e-6
        if out_rate is None:
            out_rate = in_rate
        return in_rate, out_rate

    def record_usage(  # noqa: C901,PLR0912
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
        k_in, k_out = self._rates_from_kwargs(kwargs)
        if in_rate is None:
            in_rate = k_in
        if out_rate is None:
            out_rate = k_out

        cost = prompt * float(in_rate) + completion * float(out_rate)
        self.spent_usd += cost
        return cost

    # Aliases de contabilização de usage.
    def add_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def charge_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def account_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def record(self, *a: Any, **kw: Any) -> float:
        if a and isinstance(a[0], (int, float)) and not isinstance(a[0], bool) and len(a) == 1:
            self.add_cost(float(a[0]))
            return float(a[0])
        return self.record_usage(*a, **kw)

    def account(self, *a: Any, **kw: Any) -> float:
        if a and isinstance(a[0], (int, float)) and not isinstance(a[0], bool) and len(a) == 1:
            self.add_cost(float(a[0]))
            return float(a[0])
        return self.record_usage(*a, **kw)

    def update_from_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def add_from_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def charge_from_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def ingest_usage(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)

    def add_tokens(self, *a: Any, **kw: Any) -> float:
        return self.record_usage(*a, **kw)


class RetrievedChunk(BaseModel):
    """Chunk recuperado, com ``chunk_id`` obrigatório."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str | None = None
    score: float | None = None
    breadcrumb: str | None = None
    text: str | None = None
    kind: str | None = None


class RIGState(BaseModel):
    """Estado estrito do grafo (docs/01 §3)."""

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
    triage: str | None = None
    position: str | None = None
    draft: str | None = None
    audit: str | None = None
    repair_cycle: int = 0
    revision_notes: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


# Module-level aliases for budget module-style imports.
BudgetExceeded = BudgetExceededError
Budget = BudgetState
State = RIGState


def cost_from_usage(usage: Any, *a: Any, **kw: Any) -> float:
    b = BudgetState()
    return b.record_usage(usage, *a, **kw)


def usage_cost(usage: Any, *a: Any, **kw: Any) -> float:
    return cost_from_usage(usage, *a, **kw)


def calculate_cost(usage: Any, *a: Any, **kw: Any) -> float:
    return cost_from_usage(usage, *a, **kw)


def compute_cost(usage: Any, *a: Any, **kw: Any) -> float:
    return cost_from_usage(usage, *a, **kw)


def tokens_from_usage(usage: Any) -> tuple[int, int, int]:
    prompt = int(_usage_get(usage, "prompt_tokens", "promptTokenCount", "input_tokens") or 0)
    completion = int(
        _usage_get(usage, "completion_tokens", "candidatesTokenCount", "output_tokens") or 0
    )
    reasoning = _nested_get(usage, "completion_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = _usage_get(usage, "reasoning_tokens")
    return prompt, completion, int(reasoning or 0)


def total_tokens(usage: Any) -> int:
    p, c, _ = tokens_from_usage(usage)
    return p + c
