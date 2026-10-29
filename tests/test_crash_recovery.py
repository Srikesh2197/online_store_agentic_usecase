"""Stage 7: a run killed after a committed write resumes with no duplicate write. No API calls.

A child process (tests/crash_child.py) starts a thread on a file store and dies with
os._exit at a chosen point. This process then resumes the thread from its last checkpoint,
as `arl resume` would, and checks the store. The step that was running when the process
died is re-run from its first line: for `tools`, every call of the batch.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from arl.env.seed import new_store
from arl.evals.dbdiff import diff, snapshot
from arl.framework.models import ChatSetup
from arl.framework.threads import (
    Registry,
    audit_thread,
    continue_thread,
    replay_committed,
    thread_paths,
    thread_state,
)
from arl.tracing.tracer import read_events
from crash_child import KILLED, STEPS
from fake_chat import FakeToolChatModel

CHILD = Path(__file__).parent / "crash_child.py"
SEEDED_REFUNDS = {r[0] for r in new_store().execute("SELECT id FROM refunds")}


def kill_child(root: Path, thread_id: str, where: str, keys: str = "file",
               invariants: str = "on") -> None:
    done = subprocess.run([sys.executable, str(CHILD), str(root), thread_id, where, keys,
                           invariants],
                          check=False, capture_output=True, text=True, timeout=60)
    assert done.returncode == KILLED, done.stderr


def resume(root: Path, thread_id: str, *, model_calls_made: int):
    """Continue the thread with a fresh fake model that starts where the script left off."""
    fake = FakeToolChatModel(steps=STEPS, calls=[{}] * model_calls_made)
    return continue_thread(thread_id, chat=ChatSetup(fake, "openai", "gpt-6-luna"),
                           root=root, sleep=lambda s: None)


def new_refunds(root: Path, thread_id: str) -> list[tuple[str, int]]:
    import sqlite3
    conn = sqlite3.connect(thread_paths(thread_id, root).folder / "store.db")
    rows = conn.execute("SELECT id, order_id, amount_cents FROM refunds ORDER BY id").fetchall()
    return [(order, cents) for rid, order, cents in rows if rid not in SEEDED_REFUNDS]


def refund_results(events: list[dict]) -> list[dict]:
    return [e["result"] for e in events if e["type"] == "tool_call" and e["name"] == "issue_refund"]


@pytest.mark.parametrize("where", ["after_write", "inside_tool"])
def test_a_run_killed_after_a_committed_refund_resumes_without_refunding_again(where, tmp_path):
    kill_child(tmp_path, "t-crash", where)
    registry = Registry(tmp_path)
    assert registry.get("t-crash")["status"] == "crashed"   # "running", and its process is gone
    assert new_refunds(tmp_path, "t-crash") == [("ORD-1002", 7999)]   # committed before death
    # The last checkpoint is after model call 2: the refund call's id is saved; tools is next.
    state = thread_state("t-crash", root=tmp_path)
    assert state["next"] == ("tools",) and state["values"]["model_calls"] == 2

    result = resume(tmp_path, "t-crash", model_calls_made=2)

    assert result.status == "completed" and result.reply == "I've refunded $79.99."
    assert new_refunds(tmp_path, "t-crash") == [("ORD-1002", 7999)]   # still exactly one
    events = read_events(thread_paths("t-crash", tmp_path).trace)
    # The process died inside the first call's trace block, so only the re-run is logged.
    [rerun] = refund_results(events)
    assert rerun["replayed"] is True
    if where == "after_write":   # the key's stored result is returned as it was
        assert rerun["refund"]["order_id"] == "ORD-1002" and rerun["refund"]["id"]
    else:   # killed before the result was stored: the key still stops the second refund
        assert rerun["note"] == "This call was already made; its result was not recorded."
    types = [e["type"] for e in events]
    assert types.count("run_start") == 1 and types.count("run_resume") == 1
    assert types.count("run_end") == 1 and types[-1] == "end_state"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert registry.get("t-crash")["status"] == "done"


def test_without_keys_that_survive_the_crash_the_resumed_run_refunds_twice(tmp_path):
    # The eval arms keep their keys in a TEMP table, which dies with the process.
    kill_child(tmp_path, "t-temp", "after_write", keys="temp", invariants="off")
    resume(tmp_path, "t-temp", model_calls_made=2)
    assert new_refunds(tmp_path, "t-temp") == [("ORD-1002", 7999), ("ORD-1002", 7999)]


def test_with_keys_lost_the_amount_invariant_is_the_second_line(tmp_path):
    # The same crash with the invariants on: the re-run refund would pass what was paid.
    kill_child(tmp_path, "t-inv", "after_write", keys="temp", invariants="on")
    resume(tmp_path, "t-inv", model_calls_made=2)
    assert new_refunds(tmp_path, "t-inv") == [("ORD-1002", 7999)]
    [rerun] = refund_results(read_events(thread_paths("t-inv", tmp_path).trace))
    assert rerun["error"] == "policy_violation"


def test_a_run_killed_inside_a_model_call_sends_that_call_again_and_writes_once(tmp_path):
    kill_child(tmp_path, "t-model", "in_model")
    assert new_refunds(tmp_path, "t-model") == []
    assert thread_state("t-model", root=tmp_path)["next"] == ("model",)
    result = resume(tmp_path, "t-model", model_calls_made=1)
    assert result.status == "completed" and result.model_calls == 3
    assert new_refunds(tmp_path, "t-model") == [("ORD-1002", 7999)]
    requests = [e["call_index"] for e in read_events(thread_paths("t-model", tmp_path).trace)
                if e["type"] == "model_request"]
    assert requests == [1, 2, 2, 3]   # call 2 was sent, lost with the process, and sent again


def test_the_audit_trail_of_a_resumed_run_rebuilds_its_end_state(tmp_path):
    kill_child(tmp_path, "t-audit", "after_write")
    resume(tmp_path, "t-audit", model_calls_made=2)
    audit = audit_thread("t-audit", root=tmp_path)
    assert [s["type"] for s in audit["segments"]] == ["run_start", "run_resume"]
    assert [c["tool"] for c in audit["committed"]] == ["issue_refund"]   # once, not twice
    assert any("replayed" in line for line in audit["timeline"])
    fresh = new_store()
    before = snapshot(fresh)
    replay_committed(audit, fresh)
    end_state = [e for e in read_events(thread_paths("t-audit", tmp_path).trace)
                 if e["type"] == "end_state"][-1]["db_diff"]
    assert json.loads(json.dumps(diff(before, snapshot(fresh)))) == end_state
