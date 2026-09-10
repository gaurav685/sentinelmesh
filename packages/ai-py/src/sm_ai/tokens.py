"""Token estimation and budgets.

`estimate_tokens` is a deliberately rough heuristic (~4 characters per token) —
it is used to *reject* an over-large request before any network call, not to
bill anyone. It always over- rather than under-estimates on structured text.
"""

from __future__ import annotations

from collections.abc import Iterable

from .errors import TokenBudgetExceeded
from .messages import LlmMessage, TokenUsage

__all__ = ["RunBudget", "estimate_message_tokens", "estimate_tokens"]

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # Round up, and add one per newline (structured text tends to tokenise
    # denser than prose).
    return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN + text.count("\n")


def estimate_message_tokens(messages: Iterable[LlmMessage]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(m.content) + 4  # per-message framing overhead
        for tc in m.tool_calls:
            total += estimate_tokens(tc.name) + estimate_tokens(str(tc.arguments)) + 4
    return total


class RunBudget:
    """A mutable token ceiling for one agent run or analyst request.

    `charge` is called after every LLM call; once the cumulative total crosses
    `max_total_tokens` the next `check`/`charge` raises and the run stops.
    """

    def __init__(self, *, max_total_tokens: int) -> None:
        if max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive")
        self.max_total_tokens = max_total_tokens
        self.spent = TokenUsage()

    @property
    def remaining(self) -> int:
        return max(0, self.max_total_tokens - self.spent.total)

    def check(self, prospective_prompt_tokens: int) -> None:
        if self.spent.total + prospective_prompt_tokens > self.max_total_tokens:
            raise TokenBudgetExceeded(
                f"run token budget exhausted: spent {self.spent.total}, "
                f"limit {self.max_total_tokens}, next call ~{prospective_prompt_tokens}"
            )

    def charge(self, usage: TokenUsage) -> None:
        self.spent = self.spent + usage
        if self.spent.total > self.max_total_tokens:
            raise TokenBudgetExceeded(
                f"run token budget exceeded: spent {self.spent.total}, limit {self.max_total_tokens}"
            )
