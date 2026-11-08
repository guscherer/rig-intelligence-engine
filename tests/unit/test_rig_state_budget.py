from __future__ import annotations

import os
import time

import pytest
from pydantic import ValidationError

from rig.core.config import Settings
from rig.graph.state import BudgetExceeded, BudgetState, RIGState


def test_rig_state_rejects_extra_field() -> None:
    budget = BudgetState(max_cost_usd=0.20, deadline_s=90)
    with pytest.raises(ValidationError):
        RIGState(run_id="r", doc_id="d", budget=budget, unexpected="x")


def test_budget_defaults_from_spec() -> None:
    b = BudgetState()
    assert b.max_cost_usd == 0.20
    assert b.deadline_s == 90


def test_budget_cost_overflow_raises() -> None:
    b = BudgetState(max_cost_usd=0.0, deadline_s=10**9)
    b.add_cost(0.01)
    with pytest.raises(BudgetExceeded):
        b.check()


def test_budget_deadline_overflow_raises() -> None:
    b = BudgetState(max_cost_usd=10.0, deadline_s=0)
    time.sleep(0.01)
    with pytest.raises(BudgetExceeded):
        b.check()


def test_reasoning_tokens_accounted() -> None:
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 79,
        "completion_tokens_details": {"reasoning_tokens": 63},
    }
    b = BudgetState(max_cost_usd=10.0, deadline_s=10**9)
    b.record_usage(usage)
    assert b.prompt_tokens == 100
    assert b.completion_tokens == 79
    assert b.reasoning_tokens == 63


def test_config_missing_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # also avoid .env loading by pointing to empty? Settings reads .env file; ensure env missing
    with pytest.raises(Exception) as exc:
        Settings(_env_file=os.devnull)  # type: ignore[call-arg]
    assert "DEEPSEEK_API_KEY" in str(exc.value)


def test_config_repr_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "supersecretvalue")
    s = Settings()
    assert "supersecretvalue" not in repr(s)
    assert "supersecretvalue" not in str(s)
