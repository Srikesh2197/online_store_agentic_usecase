"""The workflow: route, a fixed chain per intent, escalate otherwise. No API calls.

Driven by the scripted model through the real ChatOpenAI (tests/wire.py). A script is one
step per model call: the route (a JSON answer to the Route schema), then pick or decide if
the chain has them, then the reply. The tool calls between them are made by code.
"""

import json

import pytest

from arl.env.faults import FaultRule
from arl.env.seed import new_store
from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.tasks import by_id, load_tasks
from arl.evals.transcript import Transcript
from arl.framework.workflow import ACTIONS, ESCALATED, build_workflow, run_workflow
from arl.guardrails import ALL, Guards
from arl.guardrails.limits import Budget
from arl.tracing.tracer import Tracer, read_events
from scripted import ScriptedModel, calls, reply, truncated
from test_guarded_loop import NOTE, REFUND, refunds, store, tool_results
from wire import wire_setup

TASKS = by_id(load_tasks())


def route(intent, order_ids=(), email=None, summary="The customer's request."):
    return reply(json.dumps({"intent": intent, "order_ids": list(order_ids), "email": email,
                             "summary": summary}))


def run(*steps, ticket="A ticket.", ticket_id="t", conn=None, guards=ALL, tmp_path, **kwargs):
    model = ScriptedModel("openai", *steps)
    conn = conn or store(invariants=guards.invariants)
    before = snapshot(conn)
    tracer = Tracer("wf-run", log_dir=tmp_path)
    result = run_workflow(ticket, ticket_id=ticket_id, conn=conn, adapter=None, tracer=tracer,
                          guards=guards, chat=wire_setup(model, "openai"),
                          sleep=lambda s: None, **kwargs)
    tracer.event("end_state", db_diff=diff(before, snapshot(conn)))
    events = read_events(tracer.path)
    tracer.path.unlink()
    return result, model, conn, events


def run_task(task_id, *steps, tmp_path, **kwargs):
    task = TASKS[task_id]
    outcome = run(*steps, ticket=task.ticket.strip(), ticket_id=task.id, tmp_path=tmp_path,
                  **kwargs)
    verdict = grade(task, Transcript.from_events(outcome[3]))
    assert verdict.success, [c for c in verdict.checks if not c.passed]
    return outcome


def tools_called(events):
    return [e["name"] for e in events if e["type"] == "tool_call"]


def bound_tools(request):
    return sorted(t["name"] for t in request.get("tools", []))


# --- One chain per intent, graded by the real graders --------------------------------------

def test_status_looks_up_then_replies(tmp_path):
    result, model, _, events = run_task(
        "c01-status-shipped", route("status", ["ORD-1001"]),
        reply("Your order ORD-1001 has shipped and is on its way."), tmp_path=tmp_path)
    assert tools_called(events) == ["get_order", "get_shipment"]
    assert result.model_calls == 2 and [bound_tools(r) for r in model.requests] == [[], []]


def test_a_policy_question_needs_no_lookup(tmp_path):
    result, _, _, events = run_task(
        "c04-policy-question", route("policy_question"),
        reply("Opened items can be returned only if they are defective or arrived damaged, "
              "reported within 30 days of delivery."), tmp_path=tmp_path)
    assert tools_called(events) == [] and result.model_calls == 2


def test_an_email_only_ticket_picks_the_order(tmp_path):
    pick = reply(json.dumps({"order_ids": ["ORD-1001"]}))
    _, _, _, events = run_task(
        "c03-tracking-by-email", route("status", email="maya.chen@example.com"), pick,
        reply("Your most recent order, ORD-1001, has shipped with UPS (tracking 1Z999AA10123456784) and is in transit, "
              "expected 2026-10-07."), tmp_path=tmp_path)
    assert tools_called(events) == ["find_customer", "list_orders", "get_order", "get_shipment"]
    turns = [c.turn for c in Transcript.from_events(events).tool_calls]
    assert turns == [1, 1, 2, 2]   # the lookups after the pick are a later turn


def test_cancel_decides_with_only_its_tools_then_acts(tmp_path):
    cancel = ("cancel_order", {"order_id": "ORD-1003", "reason": "Ordered the wrong desk lamp"})
    result, model, _conn, events = run_task(
        "c07-cancel-processing", route("cancel", ["ORD-1003"]), calls(cancel),
        reply("Your order ORD-1003 is cancelled."), tmp_path=tmp_path)
    assert bound_tools(model.requests[1]) == sorted(ACTIONS["cancel"])
    assert [c.turn for c in Transcript.from_events(events).tool_calls] == [1, 2]
    assert result.model_calls == 3


def test_no_action_is_a_refusal(tmp_path):
    _, _, _, events = run_task(
        "c13-cancel-shipped", route("cancel", ["ORD-1001"]),
        reply("ORD-1001 has shipped, so it cannot be cancelled."),
        reply("I'm sorry, ORD-1001 has already shipped, so it can't be cancelled. Once it is "
              "delivered you can return it."), tmp_path=tmp_path)
    assert tools_called(events) == ["get_order"]


@pytest.mark.parametrize(("intent", "category"), sorted(ESCALATED.items()))
def test_escalate_otherwise(intent, category, tmp_path):
    _, _, conn, events = run(route(intent, ["ORD-2022"], summary="Wants a person."),
                             reply("A colleague will contact you."), tmp_path=tmp_path)
    assert tools_called(events)[-1] == "escalate_to_human"
    row = conn.execute("SELECT category, order_id FROM escalations").fetchone()
    assert (row["category"], row["order_id"]) == (category, "ORD-2022")


def test_a_person_is_requested(tmp_path):
    run_task("c19-wants-a-person", route("complaint", ["ORD-2022"]),
             reply("I've passed this to a colleague, who will contact you about ORD-2022."),
             tmp_path=tmp_path)


def test_an_unreadable_route_is_escalated(tmp_path):
    result, _, conn, events = run(reply("not json"), reply("A colleague will contact you."),
                                  tmp_path=tmp_path)
    assert next(e["intent"] for e in events if e["type"] == "route") == "unclear"
    assert any(e["type"] == "structured_output_error" for e in events)
    assert conn.execute("SELECT category FROM escalations").fetchone()[0] == "cannot_verify"
    assert result.status == "completed"


# --- Guardrails in the workflow --------------------------------------------------------------

def test_a_write_on_a_tainted_run_goes_to_a_person(tmp_path):
    steps = [route("refund_return", ["ORD-1002"]), calls(REFUND), reply("A colleague will "
                                                                         "finish this.")]
    _, _, conn, _ = run(*steps, conn=store(setup=NOTE), guards=Guards(), tmp_path=tmp_path)
    assert refunds(conn) == 1                              # off: the refund is made

    _, _, conn, events = run(*steps, conn=store(setup=NOTE), tmp_path=tmp_path)
    assert refunds(conn) == 0
    assert tools_called(events) == ["get_order", "get_shipment", "escalate_to_human"]
    assert any(e["type"] == "guard" and e.get("action") == "routed_to_person" for e in events)


def test_escalation_on_a_tainted_run_is_still_allowed(tmp_path):
    escalate = ("escalate_to_human", {"category": "policy_exception", "summary": "Outside "
                                      "policy.", "order_id": "ORD-1002", "customer_id": None})
    _, _, conn, _events = run(route("refund_return", ["ORD-1002"]), calls(escalate),
                             reply("Escalated."), conn=store(setup=NOTE), tmp_path=tmp_path)
    assert conn.execute("SELECT category FROM escalations").fetchone()[0] == "policy_exception"


def test_an_action_on_an_order_not_looked_up_is_blocked(tmp_path):
    other = ("issue_refund", {"order_id": "ORD-1001", "amount_usd": "10.00", "reason": "x"})
    _, _, conn, events = run(route("refund_return", ["ORD-1002"]), calls(other), reply("x"),
                             tmp_path=tmp_path)
    assert tool_results(events)[-1]["error"] == "unverified_order"
    assert refunds(conn, "ORD-1001") == 0


def test_a_retried_write_is_made_once(tmp_path):
    fault = [FaultRule("issue_refund", "after_commit")]
    conn = store(fault, invariants=True)
    _, _, conn, events = run(route("refund_return", ["ORD-1002"]), calls(REFUND),
                             reply("Refunded."), conn=conn, tmp_path=tmp_path)
    assert refunds(conn) == 1 and tool_results(events)[-1]["replayed"] is True
    keys = {e["key"] for e in events if e["type"] == "tool_retry"}
    assert keys == {"wf-run:call_2_0"}                     # the decide call's tool-call id


def test_the_invariants_hold_in_the_workflow(tmp_path):
    shipped = ("cancel_order", {"order_id": "ORD-1001", "reason": "Changed my mind"})
    _, _, _conn, events = run(route("cancel", ["ORD-1001"]), calls(shipped), reply("x"),
                             tmp_path=tmp_path)
    assert tool_results(events)[-1]["error"] == "policy_violation"


def test_a_budget_skips_to_the_reply(tmp_path):
    guards = Guards(limits=Budget(max_usd=0.0001))         # one scripted call is $0.00015
    result, _model, _, events = run(route("cancel", ["ORD-1003"]), reply("I could not finish."),
                                   guards=guards, tmp_path=tmp_path)
    assert (result.status, result.model_calls) == ("limit_usd", 2)
    assert tools_called(events) == []


def test_a_truncated_reply_is_retried_once(tmp_path):
    result, model, _, _ = run(route("policy_question"), truncated(text="Opened"),
                              reply("Opened items can be returned only if defective."),
                              tmp_path=tmp_path)
    assert (result.status, result.model_calls) == ("completed", 3)
    assert [r["max_output_tokens"] for r in model.requests] == [2000, 2000, 4000]


# --- Shape -------------------------------------------------------------------------------------

def test_the_graph_has_the_designed_nodes_and_no_cycle(tmp_path):
    graph = build_workflow(setup=wire_setup(ScriptedModel("openai"), "openai"), conn=new_store(),
                           tracer=Tracer("x", log_dir=tmp_path), guards=ALL,
                           echo=lambda *a: None, clock=lambda: 0.0, sleep=lambda s: None,
                           started=0.0).get_graph()
    assert set(graph.nodes) == {"__start__", "route", "gather", "pick", "decide", "act",
                                "escalate", "reply", "__end__"}
    targets = {(e.source, e.target) for e in graph.edges}
    assert ("reply", "route") not in targets and ("act", "decide") not in targets
