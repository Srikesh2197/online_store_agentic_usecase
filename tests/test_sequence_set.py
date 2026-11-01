"""The sequence set (Stage 9): two tickets from one customer, run on one store. No API calls."""

import json
from itertools import count

import pytest

from arl.env.tools import execute_tool
from arl.evals import report, runner
from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.tasks import (
    FROZEN_SEQUENCE_HASH,
    SEQUENCE_SET,
    SequenceTask,
    load_tasks,
    select,
    sequence_problems,
    task_set_hash,
)
from arl.evals.transcript import ToolCallRecord, Transcript, TurnRecord
from arl.evals.trial_env import trial_store
from arl.framework.memory import note_from, render
from arl.llm.openai_adapter import OpenAIAdapter

SEQUENCES = load_tasks(SEQUENCE_SET)


def replay_part(conn, task) -> Transcript:
    """A part's reference on `conn` (shared by both parts), graded on its own changes."""
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
    return Transcript(task.id, task.ticket, "reference", "reference", turns=turns,
                      tool_calls=calls, reply=task.reference.reply.strip(), stop="end",
                      status="completed", latency_ms=0, db_diff=diff(before, snapshot(conn)))


def test_there_are_six_sequences_and_each_is_consistent():
    assert len(SEQUENCES) == 6 and all(isinstance(s, SequenceTask) for s in SEQUENCES)
    for seq in SEQUENCES:
        assert sequence_problems(seq) == [], seq.id


@pytest.mark.parametrize("invariants", [False, True])
@pytest.mark.parametrize("seq", SEQUENCES, ids=lambda s: s.id)
def test_both_references_pass_the_real_graders_on_one_store(seq, invariants):
    first, second = seq.parts
    conn = trial_store(first, invariants=invariants)
    for task in (first, second):
        verdict = grade(task, replay_part(conn, task))
        assert verdict.success, (task.id, [c for c in verdict.checks if not c.passed])


@pytest.mark.parametrize("seq", SEQUENCES, ids=lambda s: s.id)
def test_the_history_after_ticket_1_holds_what_ticket_2_needs(seq):
    first, _ = seq.parts
    conn = trial_store(first, invariants=True)
    transcript = replay_part(conn, first)
    history = render([note_from(transcript.tool_calls, ticket=first.ticket, ticket_id=first.id,
                                customer_id=conn.env.sender_customer_id)])
    for needed in seq.needs:
        assert needed in history, (seq.id, needed, history)


@pytest.mark.parametrize("seq", SEQUENCES, ids=lambda s: s.id)
def test_ticket_2_cannot_be_answered_from_its_own_text(seq):
    """What ticket 2 needs is not in ticket 2: without the history it must come from a
    lookup the ticket does not name, or not at all."""
    _, second = seq.parts
    for needed in seq.needs:
        assert needed not in second.ticket, (seq.id, needed)


def test_the_sequence_set_is_frozen():
    if FROZEN_SEQUENCE_HASH is None:
        pytest.skip("not frozen yet: calibration first")
    assert task_set_hash(SEQUENCE_SET) == FROZEN_SEQUENCE_HASH


# --- Through the runner ---------------------------------------------------------------------------

def _scripts(monkeypatch, *scripts):
    from scripted import ScriptedModel
    from wire import wire_setup

    it = iter(scripts)
    monkeypatch.setattr("arl.framework.graph_agent.make_chat_model",
                        lambda model: wire_setup(ScriptedModel("openai", *next(it)), "openai"))


S03 = "s03-case-reference-after-escalation"


def _s03_scripts(k):
    from scripted import calls, reply

    t1 = [calls(("get_order", {"order_id": "ORD-2028"}),
                ("get_shipment", {"order_id": "ORD-2028"})),
          calls(("escalate_to_human", {"category": "policy_exception", "order_id": "ORD-2028",
                                       "customer_id": None, "summary": "Pole broken, 35 days."})),
          reply("It's past 30 days, so a colleague will look at it.")]
    t2 = [reply("Your case reference is ESC-3001.")]
    return [t1, t2] * k


@pytest.mark.parametrize("strategy", ["graph_all", "graph_memory"])
def test_a_sequence_sweep_runs_both_tickets_on_one_store(strategy, tmp_path, monkeypatch):
    _scripts(monkeypatch, *_s03_scripts(2))
    doc = runner.run_sweep(select(SEQUENCES, S03), adapter=OpenAIAdapter("gpt-6-luna", send=None),
                           trials_per_task=2, cap_usd=1.0,
                           est=runner.Estimate("gpt-6-luna", 2, 1000, 0.001, 0.05, "test"),
                           task_set=SEQUENCE_SET, results_dir=tmp_path / "results",
                           runs_dir=tmp_path / "runs", sweep_id=f"{strategy}-seq",
                           strategy=strategy)
    for trial in doc["trials"]:
        assert trial["runs"] == 2 and trial["first_success"] and trial["success"]
        assert trial["task_id"] == S03 and trial["transcript"]["task_id"] == f"{S03}.2"
        assert trial["model_calls"] == 4
        second_cost = Transcript.from_dict(trial["transcript"]).cost_usd
        assert trial["first"]["cost_usd"] > 0 and second_cost > 0
        assert trial["cost_usd"] == pytest.approx(trial["first"]["cost_usd"] + second_cost)
        # Ticket 2 is graded on its own changes: none (ticket 1's escalation is not its own).
        assert trial["transcript"]["db_diff"] == {}
        assert (trial["memory"] is not None) == (strategy == "graph_memory")
    logs = sorted(p.name for p in (tmp_path / "runs" / f"{strategy}-seq").glob("*.jsonl"))
    assert len(logs) == 4 and logs[0].endswith("-k1-t1.jsonl")
    text = report.full_report([doc])
    assert "## Sequences (two tickets, one customer)" in text
    regraded = report.load_results(tmp_path / "results" / f"{strategy}-seq.json", regrade=True)
    assert all(t["success"] and t["first_success"] for t in regraded["trials"])


def test_memory_carries_the_reference_into_ticket_2(tmp_path, monkeypatch):
    from scripted import ScriptedModel
    from wire import wire_setup

    seen = []
    scripts = iter(_s03_scripts(1))

    def make(model):
        m = ScriptedModel("openai", *next(scripts))
        seen.append(m)
        return wire_setup(m, "openai")

    monkeypatch.setattr("arl.framework.graph_agent.make_chat_model", make)
    runner.run_sweep(select(SEQUENCES, S03), adapter=OpenAIAdapter("gpt-6-luna", send=None),
                     trials_per_task=1, cap_usd=1.0,
                     est=runner.Estimate("gpt-6-luna", 1, 1000, 0.001, 0.05, "test"),
                     task_set=SEQUENCE_SET, results_dir=tmp_path / "results",
                     runs_dir=tmp_path / "runs", sweep_id="mem", strategy="graph_memory")
    assert "ESC-3001" in json.dumps(seen[1].requests[0])
    assert "ESC-3001" not in json.dumps(seen[0].requests[0])


def test_the_estimate_counts_two_runs_per_sequence(tmp_path):
    one = runner.estimate(list(load_tasks())[:6], "gpt-6-luna", 1, tmp_path, strategy="graph_all")
    two = runner.estimate(list(SEQUENCES), "gpt-6-luna", 1, tmp_path, strategy="graph_all")
    assert "x2 runs per trial" in two.basis
    assert two.per_trial_worst == pytest.approx(2 * one.per_trial_worst, rel=0.2)


def test_an_error_in_ticket_1_skips_ticket_2(tmp_path, monkeypatch):
    def broken(model):
        raise RuntimeError("API down")

    monkeypatch.setattr("arl.framework.graph_agent.make_chat_model", broken)
    counter = count()
    doc = runner.run_sweep(select(SEQUENCES, S03), adapter=OpenAIAdapter("gpt-6-luna", send=None),
                           trials_per_task=1, cap_usd=1.0,
                           est=runner.Estimate("gpt-6-luna", 1, 1000, 0.001, 0.05, "test"),
                           task_set=SEQUENCE_SET, results_dir=tmp_path / "results",
                           runs_dir=tmp_path / "runs", sweep_id=f"err{next(counter)}",
                           strategy="graph_all")
    [trial] = doc["trials"]
    assert trial["error"] and trial["runs"] == 1 and trial["success"] is None
