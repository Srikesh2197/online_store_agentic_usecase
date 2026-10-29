"""Ladder rung 3: the guarded loop (Stage 5) as a LangGraph StateGraph.

    START -> model --(stop is tool_calls, not capped)--> tools -> limits -> model
                   +--(anything else)------------------> finish -> END

The loop is the cycle: there is no `for` statement. Each part of guarded_loop.py has a place:

    model    one call (and at most one truncation retry at 2x tokens); tools are switched off
             once `cap_status` is set, so the call can only reply
    tools    every call of the last response, in order, through the same gates as the hand
             loop (loop detection, taint, grounding), retries and idempotency keys
    limits   the step cap, a detected loop and the budgets; if one trips, `cap_status` is set
             and the closing instruction is appended after the results
    finish   the exit status, as the hand loop computes it

Run-level facts live in the graph state, not in Python objects beside it, so no node or
branch can lose them, and a checkpoint (Stage 7) would hold them. Each key says how an
update is merged (its reducer): taint is OR-ed, so once set it stays set; grounded order ids
are a union; counters add. Updates are applied when a step ends, so ids seen by `tools` in
this step only ground writes in a later step: "an earlier turn", without `end_turn()`.

With every guardrail off this graph makes the same calls as hand_loop.py, and with all on
the same calls as guarded_loop.py with all on (tests/test_graph_agent.py checks both).

Stage 7 adds persistence and a person:

    model -> gate -> tools     with an approval policy, a `gate` node sits before `tools`. If
                               the policy flags a call of the batch, the gate pauses the run
                               with interrupt(); the driver shows the review packet to a
                               reviewer and resumes with the decisions, keyed by call id. A
                               rejected call is not run; an approved one passes the taint
                               block (that call only).

The run's objects (store, tracer, chat model, guards, clock) are not in closures: nodes read
them from LangGraph's runtime context, which is passed on every invoke and never saved. So the
graph is compiled once per (policy, checkpointer), and a checkpoint holds only the state. With
a checkpointer the run uses durability "sync": each step's checkpoint is written before the
next step starts, so the message holding the tool-call ids (the idempotency keys) is saved
before any of those calls runs.
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from operator import add, or_
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphDrained
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from arl.env.faults import ToolFault
from arl.env.tools import _BY_NAME, execute_tool, tool_specs
from arl.foundations.hand_loop import EXITS, MAX_STEPS
from arl.foundations.single_round import (
    CLOSING_INSTRUCTION,
    MAX_OUTPUT_TOKENS,
    Echo,
    RunResult,
    build_instructions,
)
from arl.framework.approval import REJECT, Policy, review_packet
from arl.framework.models import (
    ChatSetup,
    bind,
    make_chat_model,
    refusal_detail,
    stop_of,
    tool_calls_of,
    traced_call,
)
from arl.guardrails import OFF, Guards
from arl.guardrails.loopdetect import LoopDetector
from arl.guardrails.permissions import Taint
from arl.guardrails.prompt import DEFENCE
from arl.guardrails.retry import gave_up, with_retries
from arl.guardrails.validation import Grounding
from arl.llm.types import ToolCall, ToolChoice, ToolSpec, Usage
from arl.tracing.tracer import Tracer

# --- State ---------------------------------------------------------------------------------

def add_counts(old: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    return {key: old.get(key, 0) + new.get(key, 0) for key in old.keys() | new.keys()}


def union(old: list[str], new: list[str]) -> list[str]:
    return sorted(set(old) | set(new))


def merge(old: dict, new: dict) -> dict:
    return {**old, **new}


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   # the conversation, no system prompt
    steps: Annotated[int, add]              # loop iterations (a truncation retry is not one)
    model_calls: Annotated[int, add]
    tool_calls: Annotated[int, add]
    usage: Annotated[dict[str, int], add_counts]
    cost_usd: Annotated[float, add]
    tainted: Annotated[bool, or_]           # never cleared: OR keeps it set
    taint_sources: Annotated[list[str], add]
    grounded: Annotated[list[str], union]   # order ids returned by reads in earlier steps
    call_counts: Annotated[dict[str, int], add_counts]   # loop detection
    loop_stop: Annotated[bool, or_]
    cap_status: str | None                  # why the next call may only reply
    truncation_retried: bool
    stop: str | None                        # the neutral stop of the last response
    exit: str | None
    decisions: Annotated[dict[str, dict], merge]   # call id -> a reviewer's decision


def initial_state(ticket: str) -> AgentState:
    return AgentState(messages=[HumanMessage(ticket)], steps=0, model_calls=0, tool_calls=0,
                      usage={}, cost_usd=0.0, tainted=False, taint_sources=[], grounded=[],
                      call_counts={}, loop_stop=False, cap_status=None,
                      truncation_retried=False, stop=None, exit=None, decisions={})


@dataclass(frozen=True)
class Delegated:
    """What a delegated call (a subagent, or a handoff) did, for the tools node to merge.

    `result` is the tool result the model reads. The rest is what the call changed in the
    run: taint and grounded ids found by a subagent's reads, its model calls and spend, and
    any extra state keys (a handoff sets `active`)."""
    result: dict
    tainted: bool = False
    taint_sources: tuple[str, ...] = ()
    grounded: tuple[str, ...] = ()
    model_calls: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    update: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    """What the nodes use but a checkpoint must not hold: passed on every invoke and resume."""
    setup: ChatSetup
    conn: Any                    # the store (a sqlite3 connection carrying `env`)
    tracer: Tracer
    guards: Guards
    max_steps: int
    echo: Echo
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    started: float              # clock() at the start of the run's working time
    # Stage 8 (multi-agent). The defaults are the single agent of Stages 6 and 7 exactly.
    agent: str | None = None              # this agent's name in the trace
    tools: tuple[str, ...] | None = None  # the store tools it is offered; None: all ten
    system: str | None = None             # its system prompt; None: the policy (+ defence)
    delegates: tuple[ToolSpec, ...] = ()  # tools that run code here: subagents, handoffs
    # Runs one batch's delegated calls: (calls, state, ctx) -> {call id: Delegated}
    run_delegates: Callable | None = None


# --- The graph -----------------------------------------------------------------------------

def system_prompt(guards: Guards) -> str:
    return build_instructions() + (DEFENCE if guards.prompt else "")


def offered_specs(ctx: AgentContext) -> list[ToolSpec]:
    """The tools this agent's model is given: its store tools, then its delegated tools."""
    store = tool_specs()
    if ctx.tools is not None:
        store = [spec for spec in store if spec.name in ctx.tools]
    return store + list(ctx.delegates)


def _call_model(ctx: AgentContext, messages: list[AnyMessage], tool_choice: ToolChoice,
                max_tokens: int, index: int) -> tuple[AIMessage, Usage, float]:
    setup = ctx.setup
    chat = setup if max_tokens == MAX_OUTPUT_TOKENS else setup.with_max_tokens(max_tokens)
    specs = offered_specs(ctx)
    # An agent with no tools at all (the policy specialist) calls the model unbound.
    runnable = bind(chat, specs, tool_choice) if specs else chat.chat
    _, response, usage, cost = traced_call(
        runnable, messages, setup=setup,
        system=ctx.system or system_prompt(ctx.guards), tool_choice=tool_choice,
        max_tokens=max_tokens, index=index, tracer=ctx.tracer, echo=ctx.echo)
    return response, usage, cost


def model(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    tool_choice = "none" if state["cap_status"] else "auto"
    index = state["model_calls"] + 1
    response, usage, cost = _call_model(ctx, state["messages"], tool_choice, MAX_OUTPUT_TOKENS,
                                        index)
    stop, _ = stop_of(response, ctx.setup.provider)
    update = {"steps": 1, "model_calls": 1, "usage": asdict(usage), "cost_usd": cost}
    if stop == "max_tokens" and ctx.guards.truncation_retry and not state["truncation_retried"]:
        ctx.tracer.event("truncation_retry", max_tokens=2 * MAX_OUTPUT_TOKENS)
        response, retry_usage, retry_cost = _call_model(
            ctx, state["messages"], tool_choice, 2 * MAX_OUTPUT_TOKENS, index + 1)
        stop, _ = stop_of(response, ctx.setup.provider)
        update |= {"model_calls": 2, "usage": asdict(usage + retry_usage),
                   "cost_usd": cost + retry_cost, "truncation_retried": True}
    return update | {"messages": [response], "stop": stop}


def _wants_tools(state: AgentState) -> bool:
    return state["stop"] == "tool_calls" and not state["cap_status"]


def after_model(state: AgentState) -> str:
    return "tools" if _wants_tools(state) else "finish"


def after_model_gated(state: AgentState) -> str:
    return "gate" if _wants_tools(state) else "finish"


def rejected(decision: dict) -> dict:
    return {"error": "rejected_by_reviewer",
            "message": f"A person reviewed this action and did not approve it: "
                       f"{decision.get('reason') or 'no reason given'}. Nothing was changed. "
                       "Do not try it again. Tell the customer what was done and what was not."}


def not_available(name: str) -> dict:
    return {"error": "tool_not_available",
            "message": f"You do not have the tool '{name}'. Use only the tools you were "
                       "given. Nothing was changed."}


def act_after_reports(name: str) -> dict:
    return {"error": "wait_for_reports",
            "message": f"{name} was not run: it came in the same turn as a question to a "
                       "specialist. Read the specialists' reports first, then act in a "
                       "later turn if they support it. Nothing was changed."}


def tools_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    guards, tracer = ctx.guards, ctx.tracer
    decisions = state.get("decisions") or {}
    # The Stage 5 guardrails are objects that keep their own state. A graph keeps state in
    # the state object, so each one is rebuilt from it here and its changes written back.
    loops = taint = grounding = None
    if guards.loop_detect:
        loops = LoopDetector()
        loops.counts = Counter(state["call_counts"])
    if guards.taint:
        taint = Taint()
        taint.tainted, taint.sources = state["tainted"], list(state["taint_sources"])
    if guards.validation:
        grounding = Grounding()
        grounding.seen = set(state["grounded"])

    def guard(layer: str, call: ToolCall, result: dict) -> dict:
        tracer.event("guard", layer=layer, tool=call.name, call_id=call.id,
                     action=result["error"])
        return result

    calls = tool_calls_of(state["messages"][-1])
    delegated_names = {spec.name for spec in ctx.delegates}
    batch_delegates = any(call.name in delegated_names for call in calls)

    def gate(call: ToolCall) -> dict | None:
        decision = decisions.get(call.id)
        if (ctx.tools is not None and call.name not in ctx.tools
                and call.name not in delegated_names):
            return guard("toolset", call, not_available(call.name))
        tool = _BY_NAME.get(call.name)
        if batch_delegates and tool is not None and tool.kind != "read":
            return guard("delegation", call, act_after_reports(call.name))
        if loops and (blocked := loops.check(call.name, call.arguments)):
            return guard("loop_detect", call, blocked)
        if decision and decision["decision"] == REJECT:
            return guard("approval", call, rejected(decision))
        approved = decision is not None   # a person approved this call: taint does not block it
        if taint and not approved and (blocked := taint.check(call.name)):
            return guard("taint", call, blocked)
        if grounding and (blocked := grounding.check(call.name, call.arguments)):
            return guard("validation", call, blocked)
        return None

    def execute(call: ToolCall) -> dict:
        tool = _BY_NAME.get(call.name)
        key = (f"{tracer.run_id}:{call.id}"
               if guards.idempotency and tool is not None and tool.kind != "read" else None)

        def attempt() -> dict:
            return execute_tool(ctx.conn, call.name, call.arguments, idempotency_key=key)

        if not guards.retries:
            return attempt()
        try:
            return with_retries(
                attempt, sleep=ctx.sleep,
                on_retry=lambda n, exc: tracer.event("tool_retry", tool=call.name,
                                                     call_id=call.id, attempt=n,
                                                     fault=type(exc).__name__, key=key))
        except ToolFault as exc:
            return gave_up(call.name, tool.kind if tool else "read", exc)

    # Delegated calls (Stage 8) are gated first and then run together, before the loop
    # below logs every call in order. Only agents with delegates take this path.
    delegated: dict[str, Delegated] = {}
    if batch_delegates:
        pending = []
        for call in calls:
            if call.name in delegated_names:
                if (blocked := gate(call)) is not None:
                    delegated[call.id] = Delegated(blocked)
                else:
                    pending.append(call)
        if pending:
            delegated |= ctx.run_delegates(pending, state, ctx)
    sub = {"model_calls": 0, "tool_calls": 0, "usage": {}, "cost_usd": 0.0}
    extra_grounded: set[str] = set()
    extra_update: dict = {}

    def merge_delegated(call: ToolCall, outcome: Delegated) -> dict:
        """Fold what a subagent or handoff did into this step, in call order."""
        nonlocal extra_update
        if taint and outcome.tainted:
            if not taint.tainted:
                tracer.event("guard", layer="taint", tool=call.name, call_id=call.id,
                             action="tainted", sources=list(outcome.taint_sources))
            taint.tainted = True
            taint.sources += list(outcome.taint_sources)
        if grounding:   # ids its reads returned ground writes from the next step on
            extra_grounded.update(outcome.grounded)
        sub["model_calls"] += outcome.model_calls
        sub["tool_calls"] += outcome.tool_calls
        sub["usage"] = add_counts(sub["usage"], outcome.usage)
        sub["cost_usd"] += outcome.cost_usd
        extra_update = extra_update | outcome.update
        return outcome.result

    results = []
    for call in calls:   # in order, one at a time: one SQLite connection, as in the loop
        with tracer.tool_call(call_id=call.id, name=call.name,
                              arguments=call.arguments) as record:
            if call.id in delegated:
                result = merge_delegated(call, delegated[call.id])
            elif (result := gate(call)) is None:
                try:
                    result = execute(call)
                except Exception as exc:  # noqa: BLE001 -- as in hand_loop
                    result = {"error": "tool_failed",
                              "message": f"The tool failed: {type(exc).__name__}. "
                                         "Nothing was changed."}
                if "error" not in result:
                    if taint and taint.observe(call.name, result):
                        tracer.event("guard", layer="taint", tool=call.name,
                                     call_id=call.id, action="tainted",
                                     sources=taint.sources)
                    if grounding:
                        grounding.observe(call.name, result)
            record.finish(result=result)
        ctx.echo(f"TOOL {call.name}({call.arguments})", result)
        results.append(ToolMessage(json.dumps(result), tool_call_id=call.id,
                                   status="error" if "error" in result else "success"))

    update: dict = {"messages": results, "tool_calls": len(calls)}
    if loops:
        old = state["call_counts"]
        update |= {"call_counts": {k: n - old.get(k, 0) for k, n in loops.counts.items()
                                   if n != old.get(k, 0)},
                   "loop_stop": loops.stop}
    if taint:
        update |= {"tainted": taint.tainted,
                   "taint_sources": taint.sources[len(state["taint_sources"]):]}
    if grounding:
        grounding.end_turn()
        update["grounded"] = sorted(grounding.seen | extra_grounded)
    if delegated:   # what the subagents spent counts in this run's totals and budgets
        update |= {"model_calls": sub["model_calls"], "usage": sub["usage"],
                   "cost_usd": sub["cost_usd"],
                   "tool_calls": update["tool_calls"] + sub["tool_calls"], **extra_update}
    return update


def limits(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    guards = ctx.guards
    reason = None
    if guards.loop_detect and state["loop_stop"]:
        reason = "loop_detected"
    elif guards.limits:
        usage = state["usage"]
        reason = guards.limits.tripped(
            tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            usd=state["cost_usd"], seconds=ctx.clock() - ctx.started)
    if state["steps"] + 1 < ctx.max_steps and not reason:
        return {}
    # As at the step cap: the last calls have run, the next call may only reply.
    if reason:
        usage = state["usage"]
        ctx.tracer.event("limit", reason=reason, steps=state["model_calls"],
                         tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                         cost_usd=state["cost_usd"])
    else:
        ctx.tracer.event("step_cap", max_steps=ctx.max_steps)
    return {"cap_status": reason or "step_cap",
            "messages": [HumanMessage(CLOSING_INSTRUCTION)]}


def finish(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    last = state["messages"][-1]
    exit_ = EXITS.get(state["stop"], "stopped")
    if exit_ == "completed" and not last.text:
        exit_ = "no_reply"
    if state["cap_status"] and exit_ == "completed":
        exit_ = state["cap_status"]
    ctx.tracer.event("loop_exit", exit=exit_, steps=state["model_calls"],
                     provider_stop=stop_of(last, ctx.setup.provider)[1],
                     detail=refusal_detail(last, ctx.setup.provider))
    return {"exit": exit_}


def make_gate(policy: Policy):
    """The approval gate: pause the run if the policy flags a call of the batch.

    On resume LangGraph runs this node again from its first line, and interrupt() then
    returns the decisions instead of pausing. So nothing before interrupt() writes or logs:
    the request and the decisions are logged by the driver, outside the graph.
    """
    def gate(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        ctx = runtime.context
        tainted = ctx.guards.taint and state["tainted"]
        flagged = [(call, reasons) for call in tool_calls_of(state["messages"][-1])
                   if call.id not in state["decisions"]
                   and (reasons := policy.reasons(call, tainted=tainted))]
        if not flagged:
            return {}
        packet = review_packet(ctx.conn, ticket=state["messages"][0].text, flagged=flagged)
        answer = (interrupt(packet) or {}).get("decisions") or {}
        missing = [call.id for call, _ in flagged if call.id not in answer]
        if missing:   # an incomplete answer is not an approval
            answer = {**answer,
                      **{i: {"decision": REJECT, "reviewer": "gate",
                             "reason": "no decision was given"} for i in missing}}
        return {"decisions": {call.id: answer[call.id] for call, _ in flagged}}
    return gate


@lru_cache(maxsize=64)
def compiled_graph(policy: Policy | None = None, checkpointer=None):
    """The agent graph, compiled once per (policy, checkpointer) and reused by every run.

    Without a policy it is the Stage 6 graph exactly; with one, a gate sits before tools."""
    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("model", model)
    graph.add_node("tools", tools_node)
    graph.add_node("limits", limits)
    graph.add_node("finish", finish)
    graph.add_edge(START, "model")
    if policy is None:
        graph.add_conditional_edges("model", after_model, ["tools", "finish"])
    else:
        graph.add_node("gate", make_gate(policy))
        graph.add_conditional_edges("model", after_model_gated, ["gate", "finish"])
        graph.add_edge("gate", "tools")
    graph.add_edge("tools", "limits")
    graph.add_edge("limits", "model")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def recursion_limit(max_steps: int, gated: bool = False) -> int:
    """A backstop above any run our own cap allows (model, gate, tools, limits per step, plus
    finish). LangGraph's default is 1000; it raises GraphRecursionError, it does not reply."""
    return (5 if gated else 4) * max_steps + 5


# --- Driving a run: start, pause for a reviewer, resume, stop --------------------------------

def result_of(state: dict, ctx: AgentContext, status: str | None = None) -> RunResult:
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    return RunResult(status=status or state.get("exit"),
                     reply=(last.text if isinstance(last, AIMessage) and not status else ""),
                     stop=state.get("stop"), model_calls=state.get("model_calls", 0),
                     tool_calls=state.get("tool_calls", 0),
                     usage=Usage(**(state.get("usage") or {})),
                     cost_usd=state.get("cost_usd", 0.0),
                     latency_ms=round((ctx.clock() - ctx.started) * 1000))


def resume_with(decisions: dict) -> Command:
    """The resume value for the gate. Wrapped, because LangGraph reads a dict whose keys all
    look like interrupt ids as a map of interrupt ids, and an empty dict passes that test."""
    return Command(resume={"decisions": decisions})


MAX_REVIEWS = 2 * MAX_STEPS   # pauses in one segment; more means the gate is not taking answers


def drive(graph, run_input, config: dict, ctx: AgentContext, *, reviewer=None,
          control=None) -> RunResult:
    """Invoke the graph and answer its pauses until it ends.

    At each pause the review packet is logged (`approval_request`). With a reviewer, its
    decisions are logged (`approval_decision`) and the run resumes in this process. Without
    one, the run stops here (`run_paused`); its checkpoint waits for `arl approve`. A drain
    request (cancel) stops it at the next step boundary with its checkpoint saved."""
    tracer = ctx.tracer
    kwargs: dict = {"context": ctx}
    if graph.checkpointer is not None:
        kwargs["durability"] = "sync"
    if control is not None:
        kwargs["control"] = control
    thread_id = (config.get("configurable") or {}).get("thread_id")
    try:
        state = graph.invoke(run_input, config, **kwargs)
        reviews = 0
        while state.get("__interrupt__"):
            packet = state["__interrupt__"][0].value
            tracer.event("approval_request", thread_id=thread_id,
                         calls=[{k: c[k] for k in ("call_id", "tool", "arguments", "reasons")}
                                for c in packet["calls"]], packet=packet)
            if reviewer is None:
                tracer.event("run_paused", reason="approval", thread_id=thread_id,
                             elapsed_s=round(ctx.clock() - ctx.started, 3))
                return result_of(state, ctx, status="paused")
            reviews += 1
            if reviews > MAX_REVIEWS:
                raise RuntimeError(f"The run paused {reviews} times in one segment.")
            decisions = reviewer.review(packet)
            log_decisions(tracer, packet, decisions)
            state = graph.invoke(resume_with(decisions), config, **kwargs)
    except GraphDrained as exc:
        tracer.event("run_cancelled", reason=exc.reason, thread_id=thread_id,
                     elapsed_s=round(ctx.clock() - ctx.started, 3))
        return result_of(graph.get_state(config).values, ctx, status="cancelled")
    result = result_of(state, ctx)
    tracer.end_run(status=result.status, reply=result.reply, stop=result.stop,
                   model_calls=result.model_calls, tool_calls=result.tool_calls,
                   usage=result.usage, cost_usd=result.cost_usd, latency_ms=result.latency_ms)
    return result


def log_decisions(tracer: Tracer, packet: dict, decisions: dict) -> None:
    """Who approved what: one event per call, with the call as the reviewer saw it."""
    for call in packet["calls"]:
        d = decisions.get(call["call_id"]) or {}
        tracer.event("approval_decision", call_id=call["call_id"], tool=call["tool"],
                     arguments=call["arguments"], decision=d.get("decision"),
                     reviewer=d.get("reviewer"), reason=d.get("reason"))


def run_config(tracer: Tracer, max_steps: int, *, gated: bool, thread_id: str | None) -> dict:
    config = {"recursion_limit": recursion_limit(max_steps, gated),
              "callbacks": tracer.langchain_callbacks()}
    if thread_id is not None:
        config["configurable"] = {"thread_id": thread_id}
    return config


def run_graph_agent(
    ticket: str,
    *,
    ticket_id: str,
    conn,
    adapter,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
    guards: Guards = OFF,
    strategy: str | None = None,
    chat: ChatSetup | None = None,
    max_steps: int = MAX_STEPS,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
    policy: Policy | None = None,
    reviewer=None,
    checkpointer=None,
    control=None,
    agent_fields: dict | None = None,
) -> RunResult:
    """Run one ticket. `adapter` names the model (as for every strategy); the call itself goes
    through a LangChain chat model, `chat` if given (tests), else one built from config.

    With a `policy` the run has an approval gate and needs a checkpointer (an in-memory one
    if none is given). The thread id is the tracer's run id, so the idempotency keys
    (`run id : call id`) are the same in every process that continues the run.

    `agent_fields` (Stage 8) sets the multi-agent fields of the context: the agent's name,
    tools, prompt and delegates. The supervisor is this same run with them set."""
    if max_steps < 2:
        raise ValueError("max_steps must be at least 2: one call to act, one to reply.")
    setup = chat or make_chat_model(adapter.model)
    strategy = strategy or "graph_" + guards.name.removeprefix("guarded_")
    if policy is not None and checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()
    started = clock()
    ctx = AgentContext(setup=setup, conn=conn, tracer=tracer, guards=guards,
                       max_steps=max_steps, echo=echo, clock=clock, sleep=sleep, started=started,
                       **(agent_fields or {}))
    graph = compiled_graph(policy, checkpointer)
    with tracer.as_agent(ctx.agent), tracer.run(
            ticket_id=ticket_id, ticket=ticket, model=setup.model, provider=setup.provider,
            strategy=strategy):
        config = run_config(tracer, max_steps, gated=policy is not None,
                            thread_id=tracer.run_id if checkpointer is not None else None)
        return drive(graph, initial_state(ticket), config, ctx, reviewer=reviewer,
                     control=control)
