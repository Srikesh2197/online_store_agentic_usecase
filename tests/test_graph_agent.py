"""The graph agent (rung 3), against the hand loop and the guarded loop. No API calls.

Parity is defined on decisions, not bytes. LangChain builds its own request bodies, so they
differ from our adapters'. For one script, the two implementations must agree on:
    the tool calls (turn, name, arguments as sent) and their results;
    each model call's stop, provider stop, usage and cost;
    the exit status, reply and counts; the guard, limit and retry events (with their keys);
    which calls had tools switched off, and each call's output limit;
    the database end state.

One script drives both loops. The hand and guarded loops get `ScriptedModel` as their
adapter's `send`. The graph gets the same `ScriptedModel` behind a fake HTTP transport into
the real ChatOpenAI and ChatAnthropic (tests/wire.py), so LangChain's own request building
and response parsing are what is tested. A message-level fake (tests/fake_chat.py) is
checked once at the end.

Every on/off guardrail test of tests/test_guarded_loop.py has a twin here: the same scenario
run through guarded_loop and through the graph with the same guards, the decisions compared,
and the scenario's outcome checked again on the graph run.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from langgraph.graph import END, START, StateGraph

from arl.env.faults import FaultRule
from arl.env.seed import new_store
from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.tasks import by_id, load_tasks
from arl.evals.transcript import Transcript
from arl.foundations.guarded_loop import run_guarded_loop
from arl.foundations.hand_loop import run_hand_loop
from arl.foundations.single_round import MAX_OUTPUT_TOKENS
from arl.framework.graph_agent import AgentState, add_counts, run_graph_agent, union
from arl.framework.models import ChatSetup
from arl.guardrails import ALL, OFF, PROMPT, Guards
from arl.guardrails.limits import Budget
from arl.guardrails.prompt import DEFENCE
from arl.llm.pricing import model_entry
from arl.tracing.tracer import Tracer, read_events
from fake_chat import FakeToolChatModel
from scripted import ScriptedModel, calls, is_tool_choice_none, reply, truncated
from test_guarded_loop import (
    ADAPTERS,
    LOOK,
    NOTE,
    PROVIDERS,
    REFUND,
    SCRIPTS,
    SHIP,
    TICKET,
    Endless,
    refunds,
    store,
    tool_results,
)
from wire import wire_setup

RUN_ID = "guarded-run"   # the same run id in every loop, so idempotency keys can be compared


def run(loop: str, provider: str, *steps, guards: Guards = OFF, conn=None, model=None,
        tmp_path, ticket=TICKET, **kwargs):
    cls, model_id = ADAPTERS[provider]
    model = model or ScriptedModel(provider, *steps)
    conn = conn or new_store()
    tracer = Tracer(RUN_ID, log_dir=tmp_path / loop)
    common = {"ticket_id": "t", "conn": conn, "tracer": tracer}
    if loop == "hand":
        result = run_hand_loop(ticket, adapter=cls(model_id, send=model), **common, **kwargs)
    elif loop == "guarded":
        result = run_guarded_loop(ticket, adapter=cls(model_id, send=model), guards=guards,
                                  sleep=lambda s: None, **common, **kwargs)
    else:
        result = run_graph_agent(ticket, adapter=cls(model_id, send=None), guards=guards,
                                 chat=wire_setup(model, provider), sleep=lambda s: None,
                                 **common, **kwargs)
    events = read_events(tracer.path)
    tracer.path.unlink()
    return result, model, conn, events


EVENT_FIELDS = ("layer", "action", "reason", "exit", "key", "attempt", "fault", "max_steps",
                "max_tokens", "detail")


def _field(event: dict, name: str):
    value = event.get(name)
    if name == "detail" and isinstance(value, str) and value.startswith("{"):
        return json.loads(value)   # the Anthropic SDK re-orders stop_details' keys
    return value


def decisions(outcome) -> dict:
    result, model, conn, events = outcome
    transcript = Transcript.from_events(events)
    return {
        "calls": [(c.turn, c.name, c.arguments, c.result, c.is_error)
                  for c in transcript.tool_calls],
        "turns": [(t.index, t.stop, t.provider_stop, t.usage, t.cost_usd)
                  for t in transcript.turns],
        "run": (result.status, result.reply, result.stop, result.model_calls,
                result.tool_calls, result.usage, round(result.cost_usd, 12)),
        "events": [(e["type"], *(_field(e, f) for f in EVENT_FIELDS)) for e in events
                   if e["type"] in ("guard", "limit", "step_cap", "loop_exit", "tool_retry",
                                    "truncation_retry")],
        "tools_off": [is_tool_choice_none(r) for r in model.requests],
        "max_tokens": [r.get("max_output_tokens", r.get("max_tokens")) for r in model.requests],
        "db": snapshot(conn),
    }


def assert_same(a, b) -> None:
    da, db = decisions(a), decisions(b)
    for key in da:
        assert da[key] == db[key], key


# --- Parity with the hand loop (every guardrail off) ---------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("name", SCRIPTS)
def test_with_every_guardrail_off_it_decides_as_hand_loop(provider, name, tmp_path):
    if name == "bad json and unknown tool" and provider == "anthropic":
        pytest.skip("Anthropic sends arguments as an object, so they cannot be invalid JSON")
    assert_same(run("hand", provider, *SCRIPTS[name], tmp_path=tmp_path),
                run("graph", provider, *SCRIPTS[name], tmp_path=tmp_path))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_fault_reads_the_same_with_guardrails_off(provider, tmp_path):
    fault = [FaultRule("issue_refund", "after_commit")]
    steps = [calls(LOOK), calls(REFUND), reply("Refunded.")]
    a = run("hand", provider, *steps, tmp_path=tmp_path, conn=store(fault))
    b = run("graph", provider, *steps, tmp_path=tmp_path, conn=store(fault))
    assert_same(a, b)
    assert tool_results(b[3])[-1]["message"] == "The tool failed: ToolTimeout. Nothing was changed."


@pytest.mark.parametrize("provider", PROVIDERS)
def test_reasoning_is_replayed_on_every_later_call(provider, tmp_path):
    steps = [calls(LOOK, reasoning=True), calls(REFUND, reasoning=True), reply("Refunded.")]
    a = run("hand", provider, *steps, tmp_path=tmp_path)
    b = run("graph", provider, *steps, tmp_path=tmp_path)
    assert_same(a, b)
    second, third = (json.dumps(r) for r in b[1].requests[1:])
    first_marker, second_marker = ("enc_1", "enc_2") if provider == "openai" else ("sig_1", "sig_2")
    assert first_marker in second and first_marker in third and second_marker in third


def test_anthropic_reply_only_call_sends_tool_choice_none_as_an_object(tmp_path):
    # ChatAnthropic would read the string "none" as "force the tool named none".
    _, model, _, _ = run("graph", "anthropic", *SCRIPTS["step cap"], tmp_path=tmp_path)
    assert model.requests[-1]["tool_choice"] == {"type": "none"}
    assert [r["tool_choice"] for r in model.requests[:-1]] == [{"type": "auto"}] * 9


@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_same_tools_reach_the_model(provider, tmp_path):
    hand = run("hand", provider, reply("Hi."), tmp_path=tmp_path)[1].requests[0]
    graph = run("graph", provider, reply("Hi."), tmp_path=tmp_path)[1].requests[0]
    assert graph["tools"] == hand["tools"]
    if provider == "openai":
        assert graph["store"] is False and graph["include"] == ["reasoning.encrypted_content"]
        assert graph["parallel_tool_calls"] is True
    else:
        # The test adapters carry no request options; the config's are what make_chat_model
        # and the live adapter send.
        options = model_entry("claude-haiku-5-5")["request_options"]
        assert graph["thinking"] == options["thinking"]
        assert graph["cache_control"] == options["cache_control"]
        assert graph["max_tokens"] == hand["max_tokens"] == MAX_OUTPUT_TOKENS


# --- Guardrail twins ----------------------------------------------------------------------------

def ticking():
    ticks = iter(range(0, 10_000, 30))   # each clock read is 30 s later
    return {"clock": lambda: next(ticks)}


def lookups(n):
    return [("get_order", {"order_id": f"ORD-{2000 + n}"})]


ESCALATE = ("escalate_to_human", {"category": "other", "summary": "Refund requested.",
                                  "order_id": "ORD-1002", "customer_id": None})
SHIPPED_CANCEL = ("cancel_order", {"order_id": "ORD-1001", "reason": "Changed my mind"})
NOTE_REFUND = ("issue_refund", {"order_id": "ORD-1001", "amount_usd": "10.00", "reason": "x"})


def _status(conn, order_id):
    return conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()[0]


def _step_cap(result, model, conn, events):
    assert (result.status, result.model_calls) == ("step_cap", 10)


def _limit(status):
    def check(result, model, conn, events):
        assert result.status == status and result.model_calls < 10 and result.reply
        assert is_tool_choice_none(model.requests[-1])
        assert [e["reason"] for e in events if e["type"] == "limit"] == [status]
    return check


def _loop_detected(result, model, conn, events):
    results = tool_results(events)
    assert (result.status, result.model_calls) == ("loop_detected", 5)
    assert results[2]["error"] == "repeated_call"


def _refunds(n, order_id="ORD-1002"):
    def check(result, model, conn, events):
        assert refunds(conn, order_id) == n
    return check


def _error(index, code):
    def check(result, model, conn, events):
        assert tool_results(events)[index]["error"] == code
    return check


def _both(*checks):
    def check(*outcome):
        for c in checks:
            c(*outcome)
    return check


def _replayed_once(result, model, conn, events):
    assert refunds(conn) == 1 and tool_results(events)[1]["replayed"] is True
    call_id = next(e["call_id"] for e in events
                   if e["type"] == "tool_call" and e["name"] == "issue_refund")
    assert {e["key"] for e in events if e["type"] == "tool_retry"} == {f"{RUN_ID}:{call_id}"}


@dataclass
class Twin:
    guards: Guards
    check: Callable
    steps: list = field(default_factory=list)
    endless: Callable | None = None
    conn: Callable = store
    extra: Callable = dict
    providers: tuple = tuple(PROVIDERS)


ROUTINE = [calls(LOOK), calls(REFUND), reply("Refunded.")]

TWINS = {
    # Budgets: endless new lookups run to the step cap off, and stop early on.
    "budgets off": Twin(OFF, _step_cap, endless=lookups, extra=ticking),
    "token budget": Twin(Guards(limits=Budget(max_tokens=3_500)), _limit("limit_tokens"),
                         endless=lookups, extra=ticking),
    "dollar budget": Twin(Guards(limits=Budget(max_usd=0.0005)), _limit("limit_usd"),
                          endless=lookups, extra=ticking),
    "time budget": Twin(Guards(limits=Budget(max_seconds=100)), _limit("limit_time"),
                        endless=lookups, extra=ticking),
    # Loop detection.
    "repeats off": Twin(OFF, _step_cap, endless=lambda n: [SHIP]),
    "loop detection": Twin(Guards(loop_detect=True), _loop_detected, endless=lambda n: [SHIP]),
    # Grounding.
    "ungrounded write off": Twin(OFF, _refunds(1), [calls(REFUND), reply("Refunded.")]),
    "grounding": Twin(Guards(validation=True), _both(_refunds(0), _error(0, "unverified_order")),
                      [calls(REFUND), reply("Refunded.")]),
    "grounding, same batch": Twin(Guards(validation=True), _refunds(0),
                                  [calls(LOOK, REFUND), reply("x")]),
    "grounding, earlier turn": Twin(Guards(validation=True), _refunds(1),
                                    [calls(LOOK), calls(REFUND), reply("x")]),
    "id only in a note": Twin(Guards(validation=True),
                              _both(_error(1, "unverified_order"), _refunds(0, "ORD-1001")),
                              [calls(LOOK), calls(NOTE_REFUND), reply("x")],
                              conn=lambda: store(setup=NOTE), providers=("openai",)),
    # Retries and idempotency.
    "fault off": Twin(OFF, _error(0, "tool_failed"), [calls(LOOK), reply("Delivered.")],
                      conn=lambda: store([FaultRule("get_order", "timeout")])),
    "retries": Twin(Guards(retries=True), lambda r, m, c, e: "order" in tool_results(e)[0],
                    [calls(LOOK), reply("Delivered.")],
                    conn=lambda: store([FaultRule("get_order", "timeout")])),
    "retry without key": Twin(Guards(retries=True), _refunds(2), ROUTINE,
                              conn=lambda: store([FaultRule("issue_refund", "after_commit")])),
    "retry with key": Twin(Guards(retries=True, idempotency=True), _replayed_once, ROUTINE,
                           conn=lambda: store([FaultRule("issue_refund", "after_commit")])),
    "retries run out": Twin(Guards(retries=True, idempotency=True),
                            _both(_error(1, "outcome_unknown"), _refunds(1)), ROUTINE,
                            conn=lambda: store([FaultRule("issue_refund", "after_commit",
                                                          times="always")]),
                            providers=("openai",)),
    # Taint.
    "note off": Twin(OFF, _refunds(1), ROUTINE, conn=lambda: store(setup=NOTE)),
    "taint": Twin(Guards(taint=True),
                  _both(_refunds(0), _error(1, "blocked_untrusted_content")), ROUTINE,
                  conn=lambda: store(setup=NOTE)),
    "taint, same batch": Twin(Guards(taint=True),
                              _both(_refunds(0), _error(1, "blocked_untrusted_content")),
                              [calls(LOOK, REFUND), reply("x")], conn=lambda: store(setup=NOTE)),
    "taint allows reads and escalation": Twin(
        Guards(taint=True),
        lambda r, m, c, e: c.execute("SELECT COUNT(*) FROM escalations").fetchone()[0] == 1,
        [calls(LOOK), calls(SHIP, ESCALATE), reply("Escalated.")], conn=lambda: store(setup=NOTE)),
    "no notes, no taint": Twin(Guards(taint=True), _refunds(1), ROUTINE, providers=("openai",)),
    # Invariants (tool-side, so the graph needs nothing for them).
    "invariants off": Twin(OFF, lambda r, m, c, e: _status(c, "ORD-1001") == "cancelled",
                           [calls(("get_order", {"order_id": "ORD-1001"})), calls(SHIPPED_CANCEL),
                            reply("x")]),
    "invariants": Twin(OFF, _both(lambda r, m, c, e: _status(c, "ORD-1001") == "shipped",
                                  _error(1, "policy_violation")),
                       [calls(("get_order", {"order_id": "ORD-1001"})), calls(SHIPPED_CANCEL),
                        reply("x")], conn=lambda: store(invariants=True)),
    # Truncation.
    "truncated off": Twin(OFF, lambda r, m, c, e: r.status == "truncated",
                          [truncated(text="Your order", call=LOOK)]),
    "truncation retry": Twin(Guards(truncation_retry=True),
                             lambda r, m, c, e: (r.status, r.model_calls) == ("completed", 3),
                             [truncated(text="Your order", call=LOOK),
                              calls(LOOK), reply("Delivered.")]),
    # All on, a normal task.
    "all on, normal task": Twin(ALL, _both(_refunds(1),
                                           lambda r, m, c, e: r.status == "completed"
                                           and not any(x["type"] == "guard" for x in e)),
                                [calls(LOOK, SHIP), calls(REFUND), reply("I've refunded $79.99.")],
                                conn=lambda: store(invariants=True)),
}

TWIN_CASES = [(name, p) for name, twin in TWINS.items() for p in twin.providers]


@pytest.mark.parametrize(("name", "provider"), TWIN_CASES)
def test_guardrail_twin(name, provider, tmp_path):
    twin = TWINS[name]

    def once(loop):
        model = Endless(provider, twin.endless) if twin.endless else None
        return run(loop, provider, *twin.steps, model=model, guards=twin.guards,
                   conn=twin.conn(), tmp_path=tmp_path, **twin.extra())

    reference, graph = once("guarded"), once("graph")
    assert_same(reference, graph)
    outcome = twin.check(*graph)
    assert outcome is None or outcome is True


def test_the_twins_cover_both_settings_of_each_guardrail():
    settings = {(name, twin.guards == OFF) for name, twin in TWINS.items()}
    assert sum(off for _, off in settings) >= 6 and sum(not off for _, off in settings) >= 12


@pytest.mark.parametrize("provider", PROVIDERS)
def test_prompt_defence_is_sent_only_when_on(provider, tmp_path):
    def system(request):
        if "instructions" in request or "system" in request:
            return request.get("instructions", request.get("system"))
        return next(i["content"] for i in request["input"] if i.get("role") in ("system",
                                                                                "developer"))

    off = run("graph", provider, reply("Hi."), tmp_path=tmp_path)[1].requests[0]
    on = run("graph", provider, reply("Hi."), tmp_path=tmp_path, guards=PROMPT)[1].requests[0]
    hand = run("hand", provider, reply("Hi."), tmp_path=tmp_path)[1].requests[0]
    assert system(off) == hand.get("instructions", hand.get("system"))
    assert system(on) == system(off) + DEFENCE


# --- State and reducers -------------------------------------------------------------------------

def test_reducers():
    assert add_counts({"a": 1}, {"a": 2, "b": 1}) == {"a": 3, "b": 1}
    assert union(["ORD-1"], ["ORD-2", "ORD-1"]) == ["ORD-1", "ORD-2"]


def test_taint_cannot_be_cleared_by_a_later_node():
    graph = StateGraph(AgentState)
    graph.add_node("read_note", lambda s: {"tainted": True})
    graph.add_node("forgetful", lambda s: {"tainted": False})
    graph.add_edge(START, "read_note")
    graph.add_edge("read_note", "forgetful")
    graph.add_edge("forgetful", END)
    final = graph.compile().invoke({"tainted": False})
    assert final["tainted"] is True


# --- Grading and tracing ------------------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_scripted_graph_run_passes_the_real_graders(provider, tmp_path):
    task = by_id(load_tasks())["c07-cancel-processing"]
    conn = new_store()
    before = snapshot(conn)
    look = ("get_order", {"order_id": "ORD-1003"})
    cancel = ("cancel_order", {"order_id": "ORD-1003", "reason": "Ordered the wrong desk lamp"})
    model = ScriptedModel(provider, calls(look), calls(cancel),
                          reply("Your order ORD-1003 is cancelled."))
    cls, model_id = ADAPTERS[provider]
    tracer = Tracer("graded", log_dir=tmp_path)
    run_graph_agent(task.ticket.strip(), ticket_id=task.id, conn=conn, tracer=tracer,
                    adapter=cls(model_id, send=None), guards=ALL,
                    chat=wire_setup(model, provider))
    tracer.event("end_state", db_diff=diff(before, snapshot(conn)))
    transcript = Transcript.from_events(read_events(tracer.path))
    verdict = grade(task, transcript)
    assert verdict.success, [c for c in verdict.checks if not c.passed]
    assert transcript.strategy == "graph_all" and transcript.status == "completed"
    assert [c.turn for c in transcript.tool_calls] == [1, 2]
    assert transcript.cost_usd > 0


def test_the_trace_logs_langchains_view_of_the_request(tmp_path):
    _, _, _, events = run("graph", "openai", reply("Hi."), tmp_path=tmp_path)
    request = next(e["request"] for e in events if e["type"] == "model_request")
    assert request["via"] == "langchain" and request["tool_choice"] == "auto"
    assert request["messages"][0]["data"]["content"] == TICKET


# --- The message-level fake ---------------------------------------------------------------------

def test_the_fake_chat_model_drives_the_graph_as_the_scripted_model_drives_the_loop(tmp_path):
    steps = SCRIPTS["look, act, reply"]
    hand = run("hand", "openai", *steps, tmp_path=tmp_path)
    fake = FakeToolChatModel(steps=steps)
    tracer = Tracer(RUN_ID, log_dir=tmp_path / "fake")
    conn = new_store()
    result = run_graph_agent(TICKET, ticket_id="t", conn=conn, tracer=tracer,
                             adapter=None, chat=ChatSetup(fake, "openai", "gpt-6-luna"))
    graph_calls = [(c.turn, c.name, c.arguments, c.result)
                   for c in Transcript.from_events(read_events(tracer.path)).tool_calls]
    hand_calls = [(c.turn, c.name, c.arguments, c.result)
                  for c in Transcript.from_events(hand[3]).tool_calls]
    assert graph_calls == hand_calls
    assert (result.status, result.reply) == (hand[0].status, hand[0].reply)
    assert snapshot(conn) == snapshot(hand[2])
    assert [c["tool_choice"] for c in fake.calls] == ["auto"] * 3
    assert {c["max_tokens"] for c in fake.calls} == {MAX_OUTPUT_TOKENS}
