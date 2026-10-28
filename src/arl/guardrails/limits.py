"""Run budgets beyond the step cap: tokens, dollars and wall-clock time.

The step cap bounds how many calls a run makes, not how large they are. A run whose history
grows, or a slow provider, can cost far more than its step count suggests. A budget is
checked before each model call. When one trips, the loop stops starting new work, never
runs a call from the response that crossed the limit, and makes one reply-only call so the
customer is told honestly what was and was not done. The run's status names the limit.

Overshoot is bounded by one call plus the reply: a limit cannot interrupt a call in flight.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    # Input + output tokens summed over the run's calls. About 2x the largest normal run on
    # v1 (10,849 tokens, c12, 5 calls, Phase 3); lowered from 30,000 on 2026-10-28, before the
    # measured runs, after calibration showed 30,000 sits at the step cap of a runaway.
    max_tokens: int = 20_000
    max_usd: float = 0.01         # about 60x a measured gpt-6-luna loop run
    max_seconds: float = 120.0    # wall-clock, checked between calls

    def tripped(self, *, tokens: int, usd: float, seconds: float) -> str | None:
        """The name of the first limit reached, or None."""
        if tokens >= self.max_tokens:
            return "limit_tokens"
        if usd >= self.max_usd:
            return "limit_usd"
        if seconds >= self.max_seconds:
            return "limit_time"
        return None
