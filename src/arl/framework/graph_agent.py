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
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from operator import add, or_
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

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
from arl.llm.types import ToolCall, ToolChoice, Usage
from arl.tracing.tracer import Tracer

# --- State ---------------------------------------------------------------------------------

def add_counts(old: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    return {key: old.get(key, 0) + new.get(key, 0) for key in old.keys() | new.keys()}


def union(old: list[str], new: list[str]) -> list[str]:
    return sorted(set(old) | set(new))


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


def initial_state(ticket: str) -> AgentState:
    return AgentState(messages=[HumanMessage(ticket)], steps=0, model_calls=0, tool_calls=0,
                      usage={}, cost_usd=0.0, tainted=False, taint_sources=[], grounded=[],
                      call_counts={}, loop_stop=False, cap_status=None,
                      truncation_retried=False, stop=None, exit=None)


# --- The graph -----------------------------------------------------------------------------

def build_graph(*, setup: ChatSetup, conn, tracer: Tracer, guards: Guards, max_steps: int,
                echo: Echo, clock: Callable[[], float], sleep: Callable[[float], None],
                started: float):
    """The compiled graph for one run. Nodes close over the run's store, tracer and model."""
    system = build_instructions() + (DEFENCE if guards.prompt else "")
    tools = tool_specs()

    def call_model(messages: list[AnyMessage], tool_choice: ToolChoice, max_tokens: int,
                   index: int) -> tuple[AIMessage, Usage, float]:
        chat = setup if max_tokens == MAX_OUTPUT_TOKENS else setup.with_max_tokens(max_tokens)
        _, response, usage, cost = traced_call(
            bind(chat, tools, tool_choice), messages, setup=setup, system=system,
            tool_choice=tool_choice, max_tokens=max_tokens, index=index, tracer=tracer,
            echo=echo)
        return response, usage, cost

    def model(state: AgentState) -> dict:
        tool_choice = "none" if state["cap_status"] else "auto"
        index = state["model_calls"] + 1
        response, usage, cost = call_model(state["messages"], tool_choice, MAX_OUTPUT_TOKENS,
                                           index)
        stop, _ = stop_of(response, setup.provider)
        update = {"steps": 1, "model_calls": 1, "usage": asdict(usage), "cost_usd": cost}
        if stop == "max_tokens" and guards.truncation_retry and not state["truncation_retried"]:
            tracer.event("truncation_retry", max_tokens=2 * MAX_OUTPUT_TOKENS)
            response, retry_usage, retry_cost = call_model(
                state["messages"], tool_choice, 2 * MAX_OUTPUT_TOKENS, index + 1)
            stop, _ = stop_of(response, setup.provider)
            update |= {"model_calls": 2, "usage": asdict(usage + retry_usage),
                       "cost_usd": cost + retry_cost, "truncation_retried": True}
        return update | {"messages": [response], "stop": stop}

    def after_model(state: AgentState) -> str:
        if state["stop"] == "tool_calls" and not state["cap_status"]:
            return "tools"
        return "finish"

    def tools_node(state: AgentState) -> dict:
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

        def gate(call: ToolCall) -> dict | None:
            if loops and (blocked := loops.check(call.name, call.arguments)):
                return guard("loop_detect", call, blocked)
            if taint and (blocked := taint.check(call.name)):
                return guard("taint", call, blocked)
            if grounding and (blocked := grounding.check(call.name, call.arguments)):
                return guard("validation", call, blocked)
            return None

        def execute(call: ToolCall) -> dict:
            tool = _BY_NAME.get(call.name)
            key = (f"{tracer.run_id}:{call.id}"
                   if guards.idempotency and tool is not None and tool.kind != "read" else None)

            def attempt() -> dict:
                return execute_tool(conn, call.name, call.arguments, idempotency_key=key)

            if not guards.retries:
                return attempt()
            try:
                return with_retries(
                    attempt, sleep=sleep,
                    on_retry=lambda n, exc: tracer.event("tool_retry", tool=call.name,
                                                         call_id=call.id, attempt=n,
                                                         fault=type(exc).__name__, key=key))
            except ToolFault as exc:
                return gave_up(call.name, tool.kind if tool else "read", exc)

        results = []
        calls = tool_calls_of(state["messages"][-1])
        for call in calls:   # in order, one at a time: one SQLite connection, as in the loop
            with tracer.tool_call(call_id=call.id, name=call.name,
                                  arguments=call.arguments) as record:
                result = gate(call)
                if result is None:
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
            echo(f"TOOL {call.name}({call.arguments})", result)
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
            update["grounded"] = sorted(grounding.seen)
        return update

    def limits(state: AgentState) -> dict:
        reason = None
        if guards.loop_detect and state["loop_stop"]:
            reason = "loop_detected"
        elif guards.limits:
            usage = state["usage"]
            reason = guards.limits.tripped(
                tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                usd=state["cost_usd"], seconds=clock() - started)
        if state["steps"] + 1 < max_steps and not reason:
            return {}
        # As at the step cap: the last calls have run, the next call may only reply.
        if reason:
            usage = state["usage"]
            tracer.event("limit", reason=reason, steps=state["model_calls"],
                         tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                         cost_usd=state["cost_usd"])
        else:
            tracer.event("step_cap", max_steps=max_steps)
        return {"cap_status": reason or "step_cap",
                "messages": [HumanMessage(CLOSING_INSTRUCTION)]}

    def finish(state: AgentState) -> dict:
        last = state["messages"][-1]
        exit_ = EXITS.get(state["stop"], "stopped")
        if exit_ == "completed" and not last.text:
            exit_ = "no_reply"
        if state["cap_status"] and exit_ == "completed":
            exit_ = state["cap_status"]
        tracer.event("loop_exit", exit=exit_, steps=state["model_calls"],
                     provider_stop=stop_of(last, setup.provider)[1],
                     detail=refusal_detail(last, setup.provider))
        return {"exit": exit_}

    graph = StateGraph(AgentState)
    graph.add_node("model", model)
    graph.add_node("tools", tools_node)
    graph.add_node("limits", limits)
    graph.add_node("finish", finish)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", after_model, ["tools", "finish"])
    graph.add_edge("tools", "limits")
    graph.add_edge("limits", "model")
    graph.add_edge("finish", END)
    return graph.compile()


def recursion_limit(max_steps: int) -> int:
    """A backstop above any run our own cap allows (model + tools + limits per step, plus
    finish). LangGraph's default is 1000; it raises GraphRecursionError, it does not reply."""
    return 4 * max_steps + 5


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
) -> RunResult:
    """Run one ticket. `adapter` names the model (as for every strategy); the call itself goes
    through a LangChain chat model, `chat` if given (tests), else one built from config."""
    if max_steps < 2:
        raise ValueError("max_steps must be at least 2: one call to act, one to reply.")
    setup = chat or make_chat_model(adapter.model)
    strategy = strategy or "graph_" + guards.name.removeprefix("guarded_")
    started = clock()
    graph = build_graph(setup=setup, conn=conn, tracer=tracer, guards=guards,
                        max_steps=max_steps, echo=echo, clock=clock, sleep=sleep,
                        started=started)
    with tracer.run(ticket_id=ticket_id, ticket=ticket, model=setup.model,
                    provider=setup.provider, strategy=strategy):
        state = graph.invoke(initial_state(ticket),
                             {"recursion_limit": recursion_limit(max_steps),
                              "callbacks": tracer.langchain_callbacks()})
        last = state["messages"][-1]
        usage = Usage(**state["usage"])
        result = RunResult(status=state["exit"], reply=last.text, stop=state["stop"],
                           model_calls=state["model_calls"], tool_calls=state["tool_calls"],
                           usage=usage, cost_usd=state["cost_usd"],
                           latency_ms=round((clock() - started) * 1000))
        tracer.end_run(status=result.status, reply=result.reply, stop=result.stop,
                       model_calls=result.model_calls, tool_calls=result.tool_calls,
                       usage=usage, cost_usd=result.cost_usd, latency_ms=result.latency_ms)
    return result
