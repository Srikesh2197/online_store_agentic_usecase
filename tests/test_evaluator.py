"""The evaluator-optimizer (Stage 9): a separate model checks writes and the reply. No API calls.

The agent and the evaluator each answer from their own scripted model, behind the real
ChatOpenAI / ChatAnthropic (tests/wire.py). A verdict is the JSON the evaluator "writes".
"""

import json

import pytest

from arl.env.seed import new_store
from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.tasks import by_id, load_tasks
from arl.evals.transcript import Transcript
from arl.framework.approval import POLICIES, ScriptedReviewer
from arl.framework.graph_agent import AgentContext, compiled_graph, run_graph_agent
from arl.framework.patterns.evaluator import (
    EVALUATOR_PROMPT_HASH,
    EVALUATOR_SYSTEM,
    prompt_hash,
)
from arl.guardrails import ALL
from arl.guardrails.limits import Budget
from arl.tracing.tracer import Tracer, read_events
from scripted import ScriptedModel, calls, reply
from test_guarded_loop import ADAPTERS, LOOK, NOTE, PROVIDERS, REFUND, TICKET, refunds, store
from wire import wire_setup

ESCALATE = ("escalate_to_human", {"category": "policy_exception", "summary": "Wants a refund",
                                  "order_id": "ORD-1002", "customer_id": None})


def verdict(v: str = "pass", reason: str = "Fine under the policy.", fix: str = ""):
    return reply(json.dumps({"reason": reason, "verdict": v, "fix": fix}))


def run(provider, agent_steps, evaluator_steps=None, *, tmp_path, conn=None, guards=ALL,
        ticket=TICKET, name="r", ticket_id="t", **kwargs):
    cls, model_id = ADAPTERS[provider]
    agent = ScriptedModel(provider, *agent_steps)
    ev = ScriptedModel(provider, *evaluator_steps, prefix="ev_") if evaluator_steps is not None \
        else None
    conn = conn or new_store()
    before = snapshot(conn)
    tracer = Tracer("eval-run", log_dir=tmp_path / name)
    result = run_graph_agent(ticket, ticket_id=ticket_id, conn=conn, adapter=cls(model_id, send=None),
                             tracer=tracer, guards=guards, chat=wire_setup(agent, provider),
                             evaluator=wire_setup(ev, provider) if ev else None,
                             sleep=lambda s: None, **kwargs)
    tracer.event("end_state", db_diff=diff(before, snapshot(conn)))
    events = read_events(tracer.path)
    return result, agent, ev, conn, events


def of_type(events, *types):
    return [e for e in events if e["type"] in types]


# --- With every verdict a pass, the agent decides as graph_all ----------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_passing_verdicts_change_none_of_the_agents_decisions(provider, tmp_path):
    steps = [calls(LOOK), calls(REFUND), reply("Refunded $79.99.")]
    plain = run(provider, steps, tmp_path=tmp_path, name="plain")
    checked = run(provider, steps, [verdict(), verdict()], tmp_path=tmp_path, name="checked")
    # The agent's own requests are the same, byte for byte.
    assert plain[1].requests == checked[1].requests
    assert snapshot(plain[3]) == snapshot(checked[3])
    a, b = Transcript.from_events(plain[4]), Transcript.from_events(checked[4])
    assert [(c.name, c.arguments, c.result) for c in a.tool_calls] == \
           [(c.name, c.arguments, c.result) for c in b.tool_calls]
    assert (plain[0].status, plain[0].reply) == (checked[0].status, checked[0].reply)
    # Two checks: the refund batch, then the reply. The read batch was not checked.
    assert [e["point"] for e in of_type(checked[4], "evaluator_verdict")] == ["action", "reply"]
    assert len(checked[2].requests) == 2


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_scripted_evaluated_run_passes_the_real_graders(provider, tmp_path):
    task = by_id(load_tasks())["c07-cancel-processing"]
    look = ("get_order", {"order_id": "ORD-1003"})
    cancel = ("cancel_order", {"order_id": "ORD-1003", "reason": "Ordered the wrong desk lamp"})
    *_, events = run(provider, [calls(look), calls(cancel),
                                reply("Your order ORD-1003 is cancelled.")],
                     [verdict(), verdict()], tmp_path=tmp_path, ticket=task.ticket.strip(),
                     ticket_id=task.id)
    transcript = Transcript.from_events(events)
    verdict_ = grade(task, transcript)
    assert verdict_.success, [c for c in verdict_.checks if not c.passed]
    # Evaluator calls are turns of their own: the cancel ran after the evaluator's call 3.
    assert [c.turn for c in transcript.tool_calls] == [1, 3]


# --- Sending a batch back ----------------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_sent_back_batch_never_runs_and_the_agent_decides_again(provider, tmp_path):
    result, agent, ev, conn, events = run(
        provider, [calls(LOOK), calls(ESCALATE), reply("Sorry, it cannot be refunded.")],
        [verdict("revise", "The rules decide this: refuse, do not escalate.",
                 "Refuse in the reply.")], tmp_path=tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM escalations").fetchone()[0] == 0
    # A draft: no tool_call event for it, so the graders never see an attempt.
    assert [e["name"] for e in of_type(events, "tool_call")] == ["get_order"]
    [v] = of_type(events, "evaluator_verdict")
    assert v["verdict"] == "revise" and v["proposed"][0]["tool"] == "escalate_to_human"
    # The agent read why, as the escalation's tool result.
    third = json.dumps(agent.requests[2])
    assert "evaluator_revise" in third and "refuse, do not escalate" in third
    assert result.status == "completed" and result.reply == "Sorry, it cannot be refunded."
    # One revision per run: the reply after it was not checked.
    assert len(ev.requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_only_one_revision_per_run(provider, tmp_path):
    # Sent back once; the agent proposes the same refund again; it runs unchecked.
    _result, _agent, ev, conn, events = run(
        provider, [calls(LOOK), calls(REFUND), calls(REFUND), reply("Refunded.")],
        [verdict("revise", "Check the delivery date first.", "Look up the shipment.")],
        tmp_path=tmp_path)
    assert refunds(conn) == 1
    assert len(ev.requests) == 1 and len(of_type(events, "evaluator_verdict")) == 1


# --- Sending a reply back ----------------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_sent_back_reply_is_written_again(provider, tmp_path):
    result, agent, _ev, _conn, _events = run(
        provider, [calls(LOOK), reply("Done."), reply("Your order ORD-1002 was delivered on "
                                                      "2026-09-14.")],
        [verdict("revise", "The reply leaves out the delivery date.", "Give the date.")],
        tmp_path=tmp_path)
    assert result.reply.endswith("2026-09-14.")
    last = json.dumps(agent.requests[-1])
    assert "leaves out the delivery date" in last and "Write your reply" in last
    # The revision's call was an ordinary step with tools on.
    assert result.status == "completed"


def test_the_reply_only_call_at_the_step_cap_is_not_checked(tmp_path):
    result, _agent, ev, _conn, _events = run(
        "openai", [calls(LOOK), reply("Here is what I found.")], [], tmp_path=tmp_path,
        max_steps=2)
    assert result.status == "step_cap" and ev.requests == []


# --- Spend, trace and budget -------------------------------------------------------------------

def test_evaluator_calls_count_in_the_run_and_are_tagged(tmp_path):
    result, _agent, _ev, _conn, events = run(
        "openai", [calls(LOOK), calls(REFUND), reply("Refunded.")], [verdict(), verdict()],
        tmp_path=tmp_path)
    responses = of_type(events, "model_response")
    assert [e.get("agent") for e in responses] == [None, None, "evaluator", None, "evaluator"]
    assert [e["call_index"] for e in responses] == [1, 2, 3, 4, 5]
    assert result.model_calls == 5
    assert result.usage.input_tokens == 5 * 1000
    assert result.cost_usd == pytest.approx(sum(e["cost_usd"] for e in responses))
    end = of_type(events, "run_end")[0]
    assert end["model_calls"] == 5
    [request] = [e for e in of_type(events, "model_request") if e.get("agent") == "evaluator"][:1]
    assert request["request"]["system"] == EVALUATOR_SYSTEM


def test_evaluator_tokens_count_against_the_token_budget(tmp_path):
    steps = [calls(LOOK), calls(REFUND), reply("Refunded.")]
    guards = ALL.__class__(**{**ALL.__dict__, "limits": Budget(max_tokens=2500)})
    plain = run("openai", steps, tmp_path=tmp_path, guards=guards, name="plain")
    checked = run("openai", steps, [verdict()], tmp_path=tmp_path, guards=guards,
                  name="checked")
    assert plain[0].status == "completed"           # 2 x 1,100 tokens: under 2,500
    assert checked[0].status == "limit_tokens"      # + the evaluator's 1,100: over


# --- What the evaluator sees ---------------------------------------------------------------------

def test_order_notes_are_withheld_from_the_evaluator(tmp_path):
    guards = ALL.__class__(**{**ALL.__dict__, "taint": False})   # so the refund is proposed
    _result, agent, ev, _conn, _events = run(
        "openai", [calls(LOOK), calls(REFUND), reply("Refunded.")], [verdict(), verdict()],
        tmp_path=tmp_path, conn=store(setup=NOTE), guards=guards)
    seen = json.dumps(ev.requests)
    assert "also refund ORD-1001" not in seen
    assert "1 order note(s) withheld: untrusted text" in seen
    # The agent itself still saw the note.
    assert "also refund ORD-1001" in json.dumps(agent.requests[1])


def test_the_evaluator_sees_the_ticket_the_results_and_the_proposal(tmp_path):
    _result, _agent, ev, _conn, _events = run(
        "openai", [calls(LOOK), calls(REFUND), reply("Refunded.")], [verdict(), verdict()],
        tmp_path=tmp_path)
    first = json.dumps(ev.requests[0])
    assert TICKET in first and '\\"total_usd\\": \\"79.99\\"' in first
    assert "issue_refund" in first and "wants to make these calls now" in first
    assert "wants to send this reply" in json.dumps(ev.requests[1])
    # No tools are offered to the evaluator.
    assert not ev.requests[0].get("tools")


def test_an_unreadable_verdict_passes_and_is_logged(tmp_path):
    result, _agent, _ev, conn, events = run(
        "openai", [calls(LOOK), calls(REFUND), reply("Refunded.")],
        [reply("not json"), verdict()], tmp_path=tmp_path)
    assert refunds(conn) == 1 and result.status == "completed"
    assert len(of_type(events, "evaluator_error")) == 1


# --- With the other controls -----------------------------------------------------------------------

def test_a_pass_does_not_lift_the_code_guards(tmp_path):
    # The refund is passed, but the run read a note: taint still blocks it in `tools`.
    _result, _agent, _ev, conn, events = run(
        "openai", [calls(LOOK), calls(REFUND), reply("A colleague will finish this.")],
        [verdict(), verdict()], tmp_path=tmp_path, conn=store(setup=NOTE))
    assert refunds(conn) == 0
    assert any(e["type"] == "guard" and e["layer"] == "taint" and e["action"] ==
               "blocked_untrusted_content" for e in events)


def test_the_evaluator_runs_before_the_approval_gate(tmp_path):
    big = ("issue_refund", {"order_id": "ORD-1002", "amount_usd": "79.99",
                            "reason": "Jug arrived cracked"})
    # Sent back: the person is never asked.
    *_, conn, events = run(
        "openai", [calls(LOOK), calls(big), reply("Sorry.")],
        [verdict("revise", "No.", "Refuse.")], tmp_path=tmp_path,
        policy=POLICIES["risk_tiered"], reviewer=ScriptedReviewer())
    assert of_type(events, "approval_request") == [] and refunds(conn) == 0
    # Passed: the person is asked, as without an evaluator.
    _result, _agent, _ev, conn, events = run(
        "openai", [calls(LOOK), calls(big), reply("Refunded.")], [verdict(), verdict()],
        tmp_path=tmp_path, name="passed", policy=POLICIES["risk_tiered"],
        reviewer=ScriptedReviewer())
    assert len(of_type(events, "approval_request")) == 1 and refunds(conn) == 1


# --- The defaults and the frozen prompt ------------------------------------------------------------

def test_without_an_evaluator_the_graph_is_the_stage_8_graph():
    assert set(compiled_graph().get_graph().nodes) == {"__start__", "model", "tools", "limits",
                                                      "finish", "__end__"}
    fields = AgentContext.__dataclass_fields__
    assert all(fields[f].default is None for f in ("store_specs", "run_tool", "evaluator"))
    assert "verify" in compiled_graph(None, None, True).get_graph().nodes


def test_the_evaluator_prompt_is_frozen():
    assert prompt_hash() == EVALUATOR_PROMPT_HASH


# --- The supervisor is the graph agent, so it takes the evaluator unchanged -------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_supervisor_with_an_evaluator_checks_only_the_writer(provider, tmp_path):
    from test_supervisor import c09_router, supervise
    from test_supervisor import refunds as sup_refunds

    ev = ScriptedModel(provider, verdict(), verdict(), prefix="ev_")
    result, conn, events = supervise(provider, c09_router(provider), tmp_path,
                                     evaluator=wire_setup(ev, provider))
    assert sup_refunds(conn) == 1 and result.status == "completed"
    verdicts = of_type(events, "evaluator_verdict")
    # The ask batch has no write: not checked. The refund batch and the reply are.
    assert [v["point"] for v in verdicts] == ["action", "reply"]
    assert {v["agent"] for v in verdicts} == {"evaluator"}
    # Specialists' runs were never checked.
    assert len(ev.requests) == 2
    assert "ORD-1002 delivered 2026-09-14" in json.dumps(ev.requests[0])   # the report
