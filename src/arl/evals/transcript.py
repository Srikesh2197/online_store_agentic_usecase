"""The transcript: what the graders read about one trial.

It is built from the trial's JSONL trace, which stays the audit trail. A transcript keeps
what grading and reading need (model turns, tool calls with their results, the reply, the
database diff) and drops the raw request and response bodies, so it is small enough to
store with the results and re-grade later from a clean checkout.

A tool call's `turn` is the `call_index` of the model response that asked for it. Calls
in the same turn were sent together, before the model saw any of their results.
"""

import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TurnRecord:
    index: int
    stop: str | None
    provider_stop: str | None
    usage: dict
    cost_usd: float
    latency_ms: int


@dataclass(frozen=True)
class ToolCallRecord:
    turn: int
    name: str
    arguments: str      # the JSON string as the model sent it
    result: dict
    is_error: bool

    @property
    def args(self) -> dict | None:
        """The arguments as a dict, or None if the model sent invalid JSON."""
        try:
            value = json.loads(self.arguments)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class Transcript:
    task_id: str
    ticket: str
    model: str
    strategy: str
    turns: list[TurnRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    reply: str = ""
    stop: str | None = None          # the neutral stop reason of the last response
    status: str | None = None        # run_end status, None if the run never ended
    latency_ms: int | None = None
    db_diff: dict | None = None      # None if the end state was not recorded
    error: str | None = None         # set when the run raised (an API or harness failure)

    @property
    def cost_usd(self) -> float:
        return sum(turn.cost_usd for turn in self.turns)

    @property
    def usage(self) -> dict:
        total: dict = {}
        for turn in self.turns:
            for key, value in turn.usage.items():
                total[key] = total.get(key, 0) + value
        return total

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        return cls(**{
            **data,
            "turns": [TurnRecord(**t) for t in data.get("turns", [])],
            "tool_calls": [ToolCallRecord(**c) for c in data.get("tool_calls", [])],
        })

    @classmethod
    def from_events(cls, events: list[dict]) -> "Transcript":
        start = next(e for e in events if e["type"] == "run_start")
        fields: dict = {"task_id": start["ticket_id"], "ticket": start["ticket"],
                        "model": start["model"], "strategy": start["strategy"]}
        turns, calls, turn = [], [], 0
        for event in events:
            match event["type"]:
                case "model_response":
                    turn = event["call_index"]
                    turns.append(TurnRecord(turn, event.get("stop"), event.get("provider_stop"),
                                            event["usage"], event["cost_usd"],
                                            event["latency_ms"]))
                case "tool_call":
                    calls.append(ToolCallRecord(turn, event["name"], event["arguments"],
                                                event["result"], event["is_error"]))
                case "run_end":
                    fields |= {"reply": event["reply"], "stop": event["stop"],
                               "status": event["status"], "latency_ms": event["latency_ms"]}
                case "run_error":
                    fields["error"] = f"{event['error']}: {event['message']}"
                case "end_state":
                    fields["db_diff"] = event["db_diff"]
        return cls(**fields, turns=turns, tool_calls=calls)


def replay_reference(task) -> Transcript:
    """Run a task's reference solution against a fresh store, with no model.

    Each reference turn's calls are executed as a batch, the way the agent's tool calls
    are, so the transcript has the same shape a live run would.
    """
    from arl.env.seed import new_store
    from arl.env.tools import execute_tool
    from arl.evals.dbdiff import diff, snapshot

    conn = new_store()
    before = snapshot(conn)
    calls = []
    for index, batch in enumerate(task.reference.turns, start=1):
        for name, args in batch:
            arguments = json.dumps(args)
            result = execute_tool(conn, name, arguments)
            calls.append(ToolCallRecord(index, name, arguments, result, "error" in result))
    turns = [TurnRecord(i, "tool_calls", "reference", {}, 0.0, 0)
             for i in range(1, len(task.reference.turns) + 1)]
    turns.append(TurnRecord(len(turns) + 1, "end", "reference", {}, 0.0, 0))
    transcript = Transcript(
        task_id=task.id, ticket=task.ticket, model="reference", strategy="reference",
        turns=turns, tool_calls=calls, reply=task.reference.reply.strip(), stop="end",
        status="completed", latency_ms=0, db_diff=diff(before, snapshot(conn)),
    )
    conn.close()
    return transcript
