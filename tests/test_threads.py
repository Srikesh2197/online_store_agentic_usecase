"""Stage 7: threads from the command line: run, pause, approve, reject, cancel, resume, audit.

Each command is a separate call, with fresh objects, as separate processes would be; only the
files under the threads folder carry the run from one to the next. No API calls: the chat
model is a fake that starts where the script left off.
"""

import threading
import time

import pytest
from typer.testing import CliRunner

from arl import cli
from arl.env.seed import new_store
from arl.env.store import EnvConfig
from arl.framework.models import ChatSetup
from arl.framework.threads import (
    Registry,
    audit_thread,
    cancel_thread,
    continue_thread,
    start_thread,
    thread_paths,
    thread_state,
)
from arl.tracing.tracer import read_events
from fake_chat import FakeToolChatModel
from scripted import calls, reply

LOOK = [("get_order", {"order_id": "ORD-1002"}), ("get_shipment", {"order_id": "ORD-1002"})]
REFUND_1002 = ("issue_refund", {"order_id": "ORD-1002", "amount_usd": "79.99",
                                "reason": "Jug arrived cracked"})
REFUND_1001 = ("issue_refund", {"order_id": "ORD-1001", "amount_usd": "114.00",
                                "reason": "VIP goodwill"})
A07_STEPS = [calls(*LOOK), calls(REFUND_1002, REFUND_1001), reply("I've refunded $79.99.")]
SEEDED_REFUNDS = {r[0] for r in new_store().execute("SELECT id FROM refunds")}


@pytest.fixture
def threads_cli(tmp_path, monkeypatch):
    """The CLI with its threads under tmp_path, no Langfuse, and a fake model that continues
    the script from the number of model calls already in the thread's trace."""
    monkeypatch.setattr(cli, "_threads_root", lambda: tmp_path)
    monkeypatch.setattr("arl.tracing.tracer.langfuse_client", lambda: None)
    script = {"steps": A07_STEPS}

    def chat(model):
        made = 0
        for trace in tmp_path.glob("*/*.jsonl"):
            made = max(made, sum(e["type"] == "model_response" for e in read_events(trace)))
        return ChatSetup(FakeToolChatModel(steps=script["steps"], calls=[{}] * made),
                         "openai", "gpt-6-luna")

    monkeypatch.setattr(cli, "_chat", chat)
    runner = CliRunner()

    def invoke(*args, ok=True):
        result = runner.invoke(cli.app, list(args))
        if ok:
            assert result.exit_code == 0, result.output + repr(result.exception)
        return result

    invoke.root, invoke.script = tmp_path, script
    return invoke


def new_refunds(root, thread_id):
    import sqlite3
    conn = sqlite3.connect(thread_paths(thread_id, root).folder / "store.db")
    return [(o, c) for i, o, c in conn.execute("SELECT id, order_id, amount_cents FROM refunds")
            if i not in SEEDED_REFUNDS]


def start_a07(arl, thread="T1"):
    out = arl("run", "--task", "a07", "--strategy", "graph_approve_risk", "--thread", thread,
              "-q").output
    assert "WAITING FOR APPROVAL" in out and f"arl approve {thread}" in out
    assert "NOTE from warehouse (not written by the customer)" in out   # the reviewer sees why
    return out


def test_a_paused_thread_is_listed_and_approving_one_call_finishes_the_run(threads_cli):
    arl = threads_cli
    start_a07(arl)
    assert Registry(arl.root).get("T1")["status"] == "paused"
    assert "T1" in arl("threads", "--pending").output
    assert new_refunds(arl.root, "T1") == []   # nothing is written while it waits

    out = arl("approve", "T1", "--call", "call_2_0", "--reason", "matches the ticket",
              "--reviewer", "alice", "-y").output

    assert "I've refunded $79.99." in out
    assert new_refunds(arl.root, "T1") == [("ORD-1002", 7999)]
    audit = audit_thread("T1", root=arl.root)
    assert [(a["reviewer"], a["decision"], a["arguments"]["order_id"]) for a in
            audit["approvals"]] == [("alice", "approve", "ORD-1002"),
                                    ("alice", "reject", "ORD-1001")]
    assert [s["type"] for s in audit["segments"]] == ["run_start", "run_resume"]
    assert audit["status"] == "completed"
    assert Registry(arl.root).get("T1")["status"] == "done"
    assert "Nothing is waiting" in arl("threads", "--pending").output
    text = arl("audit", "T1").output
    assert "alice: approve issue_refund" in text and "alice: reject issue_refund" in text


def test_rejecting_writes_nothing_and_the_model_still_replies(threads_cli):
    arl = threads_cli
    start_a07(arl)
    out = arl("reject", "T1", "--reason", "a person will handle it", "--reviewer", "bob",
              "-y").output
    assert "I've refunded $79.99." in out   # the scripted reply; the store says otherwise
    assert new_refunds(arl.root, "T1") == []
    events = read_events(thread_paths("T1", arl.root).trace)
    results = [e["result"] for e in events if e["type"] == "tool_call"
               and e["name"] == "issue_refund"]
    assert [r["error"] for r in results] == ["rejected_by_reviewer"] * 2
    assert "a person will handle it" in results[0]["message"]


def test_approve_needs_a_paused_thread_and_a_known_call(threads_cli):
    arl = threads_cli
    start_a07(arl)
    assert arl("approve", "T1", "--call", "nope", "-y", ok=False).exit_code != 0
    arl("approve", "T1", "-y")
    assert arl("approve", "T1", "-y", ok=False).exit_code != 0   # done, not paused


def test_cancelling_a_paused_thread_keeps_its_state_and_it_can_be_resumed(threads_cli):
    arl = threads_cli
    start_a07(arl)
    assert "is cancelled" in arl("cancel", "T1", "--reviewer", "carol").output
    assert Registry(arl.root).get("T1")["status"] == "cancelled"
    state = thread_state("T1", root=arl.root)
    assert state["next"] == ("gate",) and state["values"]["tainted"] is True
    assert "Last checkpoint: next ('gate',)" in arl("audit", "T1", "--state").output
    events = read_events(thread_paths("T1", arl.root).trace)
    assert events[-1]["type"] == "run_cancelled" and "carol" in events[-1]["reason"]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    # Resuming runs the gate again: it asks again, nothing was decided while cancelled.
    assert "WAITING FOR APPROVAL" in arl("resume", "T1").output
    assert new_refunds(arl.root, "T1") == []


class SlowChat(FakeToolChatModel):
    delay: float = 0.6

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        time.sleep(self.delay)
        return super()._generate(messages, stop, run_manager, **kwargs)


def test_cancelling_a_running_thread_stops_it_at_the_next_step_with_its_state_kept(tmp_path):
    steps = [calls(LOOK[0]), calls(REFUND_1002), reply("Refunded.")]
    done = {}

    def run():   # the store is made in the worker: a SQLite connection is thread-bound
        source = new_store()
        source.env = EnvConfig(invariants=True)
        done["result"] = start_thread(
            "The blender in ORD-1002 arrived with a cracked jug. Refund it.", ticket_id="t",
            source_store=source, chat=ChatSetup(SlowChat(steps=steps), "openai", "gpt-6-luna"),
            strategy="graph_all", thread_id="T2", root=tmp_path, sleep=lambda s: None)

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.time() + 5
    while time.time() < deadline:   # wait until the run is in its first model call
        try:
            if Registry(tmp_path).get("T2")["status"] == "running":
                break
        except KeyError:
            pass
        time.sleep(0.05)
    assert cancel_thread("T2", who="dave", root=tmp_path) == "requested"
    worker.join(timeout=10)

    assert done["result"].status == "cancelled" and done["result"].model_calls == 1
    assert Registry(tmp_path).get("T2")["status"] == "cancelled"
    assert thread_state("T2", root=tmp_path)["next"] == ("tools",)   # drained before tools
    assert new_refunds(tmp_path, "T2") == []
    events = read_events(thread_paths("T2", tmp_path).trace)
    assert events[-1]["type"] == "run_cancelled" and events[-1]["reason"] == "cancelled by dave"

    result = continue_thread("T2", chat=ChatSetup(FakeToolChatModel(steps=steps, calls=[{}]),
                                                  "openai", "gpt-6-luna"),
                             root=tmp_path, sleep=lambda s: None)
    assert result.status == "completed" and result.reply == "Refunded."
    assert new_refunds(tmp_path, "T2") == [("ORD-1002", 7999)]


def test_a_resumed_segment_keeps_counting_the_agents_working_time_not_the_wait(threads_cli):
    arl = threads_cli
    start_a07(arl)
    paused_after = Registry(arl.root).get("T1")["elapsed_s"]
    time.sleep(0.3)   # the reviewer takes their time
    arl("approve", "T1", "--call", "call_2_0", "-y")
    events = read_events(thread_paths("T1", arl.root).trace)
    total = [e for e in events if e["type"] == "run_end"][-1]["latency_ms"] / 1000
    assert paused_after <= total < paused_after + 0.3
