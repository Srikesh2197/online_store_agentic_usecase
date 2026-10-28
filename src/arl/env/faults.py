"""A seeded fault injector: the tools' backend failing on purpose.

Real tools sit on services that time out or return server errors. Three kinds of failure
matter to an agent, because each needs a different response:

    timeout       the call never reached the service: nothing happened, a retry is safe
    unavailable   the service answered "try again later" (a 503): nothing happened
    after_commit  the service did the work, then the reply was lost: something DID happen,
                  but the caller sees the same timeout as in the first case

The third is why a blind retry can refund twice, and why write tools take idempotency keys.

A fault plan belongs to a task, not to an agent: every arm of an experiment meets the same
faults. Rules are deterministic ("the 1st call of issue_refund fails once"). An optional
`rate` adds random faults from a seeded generator, so a run is still reproducible.
"""

import random
from dataclasses import dataclass, field
from typing import Literal

FaultKind = Literal["timeout", "unavailable", "after_commit"]
KINDS: tuple[FaultKind, ...] = ("timeout", "unavailable", "after_commit")


class ToolFault(Exception):
    """A transient failure of a tool's backend. Raised by execute_tool, never returned."""

    kind: FaultKind = "timeout"


class ToolTimeout(ToolFault, TimeoutError):
    kind = "timeout"


class ToolUnavailable(ToolFault):
    kind = "unavailable"


@dataclass(frozen=True)
class FaultRule:
    tool: str
    kind: FaultKind
    nth: int = 1                        # the first attempt it hits, counting from 1 per tool
    times: int | Literal["always"] = 1  # how many attempts in a row it hits

    def hits(self, attempt: int) -> bool:
        if attempt < self.nth:
            return False
        return self.times == "always" or attempt < self.nth + self.times


@dataclass
class FaultInjector:
    rules: list[FaultRule] = field(default_factory=list)
    rate: float = 0.0                   # chance of a random fault on any attempt
    seed: int = 0
    attempts: dict[str, int] = field(default_factory=dict)
    fired: list[dict] = field(default_factory=list)   # what was injected, for the trace

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    @classmethod
    def from_specs(cls, specs: list[dict], rate: float = 0.0, seed: int = 0) -> "FaultInjector":
        return cls([FaultRule(**spec) for spec in specs], rate, seed)

    def next_fault(self, tool: str) -> FaultKind | None:
        """Count one attempt at `tool` and say which fault, if any, hits it."""
        attempt = self.attempts.get(tool, 0) + 1
        self.attempts[tool] = attempt
        kind = next((rule.kind for rule in self.rules
                     if rule.tool == tool and rule.hits(attempt)), None)
        if kind is None and self.rate and self._rng.random() < self.rate:
            kind = self._rng.choice(KINDS)
        if kind:
            self.fired.append({"tool": tool, "attempt": attempt, "kind": kind})
        return kind


def raise_fault(kind: FaultKind, tool: str) -> None:
    if kind == "unavailable":
        raise ToolUnavailable(f"{tool}: the service is temporarily unavailable (503)")
    raise ToolTimeout(f"{tool}: no response before the timeout")
