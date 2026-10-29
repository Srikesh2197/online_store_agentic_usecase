"""Stage 7: what a checkpoint holds, how it is written, and what the audit trail rebuilds.
No API calls."""

import json

from langgraph.graph.state import CompiledStateGraph

from arl.env.tools import _BY_NAME
from arl.evals.dbdiff import diff, snapshot
from arl.evals.tasks import by_id, load_tasks
from arl.evals.trial_env import trial_store
from arl.framework.approval import RISK_TIERED, ScriptedReviewer
from arl.framework.graph_agent import AgentState, compiled_graph, run_graph_agent
from arl.framework.models import ChatSetup
from arl.framework.threads import checkpointer, reconstruct, replay_committed
from arl.guardrails import ALL
from arl.tracing.tracer import Tracer, read_events
from fake_chat import FakeToolChatModel
from scripted import calls, reply

A07 = by_id(load_tasks("adversarial"))["a07-indirect-note-with-valid-refund"]
STEPS = [calls(("get_order", {"order_id": "ORD-1002"}), ("get_shipment", {"order_id": "ORD-1002"})),
         calls(("issue_refund", {"order_id": "ORD-1002", "amount_usd": "79.99",
                                 "reason": "Jug arrived cracked"}),
               ("issue_refund", {"order_id": "ORD-1001", "amount_usd": "114.00",
                                 "reason": "VIP"})),
         reply("I've refunded $79.99.")]


def run_a07(tmp_path, *, policy=RISK_TIERED, saver=None, run_id="cp-1"):
    conn = trial_store(A07, invariants=True)
    before = snapshot(conn)
    tracer = Tracer(run_id, log_dir=tmp_path)
    chat = ChatSetup(FakeToolChatModel(steps=STEPS), "openai", "gpt-6-luna")
    result = run_graph_agent(A07.ticket, ticket_id=A07.id, conn=conn, adapter=None,
                             tracer=tracer, guards=ALL, chat=chat, policy=policy,
                             reviewer=ScriptedReviewer(), checkpointer=saver,
                             sleep=lambda s: None)
    return result, conn, before, read_events(tracer.path)


def test_a_checkpoint_holds_the_state_and_nothing_of_the_run_context(tmp_path):
    saver = checkpointer(str(tmp_path / "checkpoints.sqlite"))
    run_a07(tmp_path, saver=saver)
    snap = compiled_graph(RISK_TIERED, saver).get_state({"configurable": {"thread_id": "cp-1"}})
    assert set(snap.values) == set(AgentState.__annotations__)
    assert snap.values["tainted"] is True and "ORD-1002" in snap.values["grounded"]
    assert {d["decision"] for d in snap.values["decisions"].values()} == {"approve", "reject"}
    assert snap.next == ()   # finished
    history = list(compiled_graph(RISK_TIERED, saver).get_state_history(
        {"configurable": {"thread_id": "cp-1"}}))
    assert len(history) > 8   # one checkpoint per step: model, gate, tools, limits, ...
    raw = (tmp_path / "checkpoints.sqlite").read_bytes()
    assert b"sqlite3.Connection" not in raw and b"Tracer" not in raw


def test_checkpointed_runs_save_each_step_before_the_next_and_others_are_unchanged(
        tmp_path, monkeypatch):
    seen = []
    real = CompiledStateGraph.invoke

    def spy(self, *args, **kwargs):
        seen.append(kwargs.get("durability"))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(CompiledStateGraph, "invoke", spy)
    run_a07(tmp_path, saver=checkpointer(str(tmp_path / "cp.sqlite")))
    assert seen and set(seen) == {"sync"}   # the first invoke and each resume
    seen.clear()
    run_a07(tmp_path, policy=None, run_id="cp-2")   # graph_all as in Stage 6
    assert seen == [None]


def test_the_audit_trail_of_an_approval_run_rebuilds_it(tmp_path):
    result, conn, before, events = run_a07(tmp_path)
    audit = reconstruct(events)
    assert audit["ticket"] == A07.ticket and audit["status"] == "completed"
    assert audit["reply"] == result.reply
    approved = {a["call_id"] for a in audit["approvals"] if a["decision"] == "approve"}
    gated_writes = [c for c in audit["committed"] if _BY_NAME[c["tool"]].kind == "write"]
    assert gated_writes and {c["call_id"] for c in gated_writes} <= approved
    assert all(a["reviewer"] == "scripted-v1" and a["reason"] for a in audit["approvals"])
    # The committed changes, replayed on a fresh copy of the store, give the same end state.
    fresh = trial_store(A07, invariants=True)
    replay_committed(audit, fresh)
    assert json.dumps(diff(before, snapshot(fresh))) == json.dumps(diff(before,
                                                                        snapshot(conn)))
