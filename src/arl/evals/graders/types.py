"""What a grader returns."""

from dataclasses import asdict, dataclass

GROUPS = ("db", "facts", "hygiene", "trajectory")


@dataclass(frozen=True)
class Check:
    group: str      # one of GROUPS: the component of success this check belongs to
    name: str
    passed: bool
    detail: str     # why it passed or failed, in words a reader can act on


@dataclass(frozen=True)
class Verdict:
    checks: list[Check]
    error: str | None = None    # the trial failed for a reason outside the agent (API, harness)

    @property
    def success(self) -> bool | None:
        """All checks pass. None for an error trial, which is left out of the rates."""
        if self.error:
            return None
        return all(check.passed for check in self.checks)

    def group_passed(self, group: str) -> bool | None:
        if self.error:
            return None
        return all(c.passed for c in self.checks if c.group == group)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]

    def to_dict(self) -> dict:
        return {"success": self.success, "error": self.error,
                "groups": {g: self.group_passed(g) for g in GROUPS},
                "checks": [asdict(c) for c in self.checks]}

    @classmethod
    def from_dict(cls, data: dict) -> "Verdict":
        return cls([Check(**c) for c in data["checks"]], data.get("error"))
