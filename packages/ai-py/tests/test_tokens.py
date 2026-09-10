from __future__ import annotations

import pytest

from sm_ai.errors import TokenBudgetExceeded
from sm_ai.messages import LlmMessage, MessageRole, TokenUsage
from sm_ai.tokens import RunBudget, estimate_message_tokens, estimate_tokens


def test_estimate_tokens_grows_with_length_and_is_never_negative() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") >= 1
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)


def test_estimate_message_tokens_counts_every_turn() -> None:
    msgs = [
        LlmMessage(role=MessageRole.system, content="you are an analyst"),
        LlmMessage(role=MessageRole.user, content="x" * 400),
    ]
    assert estimate_message_tokens(msgs) > estimate_tokens("x" * 400)


def test_run_budget_check_rejects_before_the_call() -> None:
    b = RunBudget(max_total_tokens=100)
    b.check(90)  # ok
    with pytest.raises(TokenBudgetExceeded):
        b.check(200)


def test_run_budget_charge_accumulates_and_trips() -> None:
    b = RunBudget(max_total_tokens=50)
    b.charge(TokenUsage(prompt_tokens=20, completion_tokens=10))
    assert b.spent.total == 30
    assert b.remaining == 20
    with pytest.raises(TokenBudgetExceeded):
        b.charge(TokenUsage(prompt_tokens=30, completion_tokens=0))


def test_run_budget_rejects_a_non_positive_ceiling() -> None:
    with pytest.raises(ValueError, match="positive"):
        RunBudget(max_total_tokens=0)
