"""Hand-made tasks and transcripts for the grader tests."""

import json

from arl.evals.tasks import Task
from arl.evals.transcript import ToolCallRecord, Transcript, TurnRecord


def make_task(**overrides) -> Task:
    data = {
        "id": "t-test",
        "title": "test",
        "category": "write",
        "provenance": "test",
        "ticket": "Refund ORD-1002",
        "expected": {"disposition": "resolved"},
        "reference": {"turns": [], "reply": "ok"},
    }
    return Task.model_validate({**data, **overrides})


def call(turn: int, name: str, is_error: bool = False, result: dict | None = None,
         **args) -> ToolCallRecord:
    result = result or ({"error": "x", "message": "y"} if is_error else {"ok": True})
    return ToolCallRecord(turn, name, json.dumps(args), result, is_error)


def make_transcript(*calls: ToolCallRecord, reply: str = "Done.", stop: str = "end",
                    db_diff: dict | None = None, task_id: str = "t-test",
                    error: str | None = None) -> Transcript:
    last = max((c.turn for c in calls), default=0) + 1
    turns = [TurnRecord(i, "tool_calls", "completed", {}, 0.0, 0) for i in range(1, last)]
    turns.append(TurnRecord(last, stop, "completed", {}, 0.0, 0))
    return Transcript(task_id, "ticket", "test-model", "single_round", turns=turns,
                      tool_calls=list(calls), reply=reply, stop=stop, status="completed",
                      latency_ms=1, db_diff={} if db_diff is None else db_diff, error=error)


def refund_row(order_id: str = "ORD-1002", cents: int = 7999) -> dict:
    return {"id": "REF-9002", "order_id": order_id, "amount_cents": cents,
            "reason": "cracked", "status": "issued", "created_at": "2026-10-05"}


def inserted(table: str, *rows: dict) -> dict:
    return {table: {"insert": list(rows), "delete": [], "update": {}}}


def updated(table: str, row_id: str, **changes) -> dict:
    return {table: {"insert": [], "delete": [], "update": {row_id: changes}}}
