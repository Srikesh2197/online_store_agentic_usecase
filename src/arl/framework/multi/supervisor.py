"""Orchestrator-workers: a supervisor whose tools include agents (Stage 8, rung 4).

The supervisor is the graph agent of graph_agent.py with a different context: it is offered
the write tools, escalation and three specialists (ask_orders, ask_refunds, ask_policy), and
no lookup tools, so it must delegate. It is the only writer.

A specialist is the same compiled graph again, run from inside the supervisor's `tools` node
with its own context: its prompt, its read-only tools, and one message, the supervisor's
brief. It never sees the ticket or the other specialists. Its final reply is the tool
result the supervisor reads.

    supervisor: model -> tools -> limits -> model ... -> finish
                           |
                           +-- ask_orders(brief) ----> [orders:  model -> tools -> ... -> finish]
                           +-- ask_refunds(brief) ---> [refunds: model -> tools -> ... -> finish]
                                 (same turn: run at the same time, in threads)

What crosses from a specialist back to the run (graph_agent.Delegated):
    taint        OR-ed into the supervisor's state: a note read by a specialist blocks the
                 supervisor's later writes (the Rule of Two at run level)
    grounded     order ids its reads returned ground the supervisor's writes from its next step
    spend        model calls, tokens and dollars count in the run's totals and its budget

Threads. Specialists asked in one turn run at the same time in a ContextThreadPoolExecutor,
which copies contextvars into each thread, so LangChain callbacks and Langfuse spans stay
nested under the supervisor's `tools` node. The trial's SQLite connection belongs to the
main thread, so each specialist reads its own copy, taken just before it starts. The copy is
exact: specialists only read, and no write can run in a turn that asks a specialist
(graph_agent's `act_after_reports`). Each specialist logs into a buffered tracer; afterwards
the main thread appends the buffers in call order, numbering model calls on from the run's
count, so the trace does not depend on which thread finished first.

Budget. The run has one pool (tokens, dollars, time). Specialists running at the same time
cannot see each other's spend, so the pool left is split equally between them: each one's
`limits` node trips at its share.

Nothing is numbered in a closure: delegations so far and call offsets are read from state.
A specialist run is not checkpointed. Its config names its own thread id, so LangGraph runs
it as a fresh root graph (not a subgraph of the supervisor's checkpointed thread), with the
context it is given.
"""

import json
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import ContextThreadPoolExecutor

from arl.env.store import Store, env_of
from arl.framework.graph_agent import (
    Delegated,
    compiled_graph,
    initial_state,
    recursion_limit,
    run_graph_agent,
)
from arl.framework.models import tool_calls_of
from arl.framework.multi import MAX_DELEGATIONS, SUB_MAX_STEPS
from arl.framework.multi.specialists import (
    BY_TOOL,
    ESCALATE,
    MULTI_GUARDS,
    SPECIALISTS,
    WRITES,
    supervisor_system,
)

STRATEGY = "supervisor"


# --- The store, shared safely ---------------------------------------------------------------

class LockedFaults:
    """The trial's fault injector behind a lock, so threads keep its counts consistent."""

    def __init__(self, faults, lock: threading.Lock):
        self._faults, self._lock = faults, lock

    def next_fault(self, name: str):
        with self._lock:
            return self._faults.next_fault(name)

    @property
    def fired(self):
        return self._faults.fired


def store_copy(conn: sqlite3.Connection, lock: threading.Lock) -> sqlite3.Connection:
    """A copy of the store a worker thread may read, with the same environment."""
    copy = sqlite3.connect(":memory:", factory=Store, check_same_thread=False)
    conn.backup(copy)
    copy.row_factory = sqlite3.Row
    copy.execute("PRAGMA foreign_keys = ON")
    env = env_of(conn)
    copy.env = replace(env, faults=LockedFaults(env.faults, lock)) if env.faults else env
    return copy


# --- Reading the run's state ------------------------------------------------------------------

def delegations_so_far(state: dict) -> int:
    """Specialist calls in earlier turns (the last message is this turn's batch)."""
    return sum(1 for m in state["messages"][:-1] if isinstance(m, AIMessage)
               for c in tool_calls_of(m) if c.name in BY_TOOL)


def tokens_of(usage: dict) -> int:
    return usage.get("input_tokens", 0) + usage.get("output_tokens", 0)


def pool_seed(state: dict, ctx, n: int) -> dict:
    """The usage a specialist starts from, so that its own `limits` node trips when it has
    spent its share of what is left of the run's pool. With one specialist that is the run's
    totals exactly."""
    limits = ctx.guards.limits
    if limits is None:
        return {"usage": {}, "cost_usd": 0.0}
    left_tokens = max(0, limits.max_tokens - tokens_of(state["usage"]))
    left_usd = max(0.0, limits.max_usd - state["cost_usd"])
    return {"usage": {"input_tokens": limits.max_tokens - left_tokens // n},
            "cost_usd": limits.max_usd - left_usd / n}


def _error(code: str, message: str) -> dict:
    return {"error": code, "message": message}


def _brief(call, field: str) -> str | None:
    try:
        args = json.loads(call.arguments)
    except (json.JSONDecodeError, TypeError):
        return None
    value = args.get(field) if isinstance(args, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


# --- Running specialists -----------------------------------------------------------------

def _run_specialist(spec, call, brief: str, ctx, conn, tracer, seed: dict) -> dict:
    """One specialist, start to report, in the calling (worker) thread."""
    sub_ctx = replace(ctx, conn=conn, tracer=tracer, agent=spec.name, tools=spec.tools,
                      system=spec.system(ctx.guards), delegates=(), run_delegates=None,
                      max_steps=SUB_MAX_STEPS)
    state = initial_state(brief) | seed
    config = {"recursion_limit": recursion_limit(SUB_MAX_STEPS),
              "run_name": f"agent:{spec.name}",
              # A thread id of its own: a fresh root run, never part of the parent's thread.
              "configurable": {"thread_id": f"{ctx.tracer.run_id}:{call.id}"}}
    return compiled_graph().invoke(state, config, context=sub_ctx)


def _timed(fn, *args) -> tuple:
    started_wall = datetime.now(UTC).isoformat(timespec="milliseconds")
    start = time.perf_counter()
    try:
        return "ok", fn(*args), started_wall, round((time.perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 -- re-raised by the main thread after the merge
        return "error", exc, started_wall, round((time.perf_counter() - start) * 1000)


def _report(final: dict) -> dict:
    last = final["messages"][-1]
    text = last.text if isinstance(last, AIMessage) else ""
    out = {"status": final.get("exit"), "report": text}
    if final.get("exit") != "completed":
        out["note"] = "The specialist stopped early; its report may be incomplete."
    return out


def _delta(final: dict, seed: dict, report: dict, agent: str) -> Delegated:
    usage = {k: v - seed["usage"].get(k, 0) for k, v in final["usage"].items()}
    return Delegated({"agent": agent, **report}, tainted=final["tainted"],
                     taint_sources=tuple(final["taint_sources"]),
                     grounded=tuple(final["grounded"]), model_calls=final["model_calls"],
                     tool_calls=final["tool_calls"], usage=usage,
                     cost_usd=final["cost_usd"] - seed["cost_usd"])


def make_delegate_runner(max_workers: int | None = None):
    """The supervisor's `run_delegates`: gate, run (concurrently), merge traces, in order.

    `max_workers=1` runs the specialists one after another on the same code path."""

    def run_delegates(calls, state, ctx) -> dict[str, Delegated]:
        out: dict[str, Delegated] = {}
        tracer = ctx.tracer
        limits = ctx.guards.limits
        spent = (limits.tripped(tokens=tokens_of(state["usage"]), usd=state["cost_usd"],
                                seconds=ctx.clock() - ctx.started) if limits else None)
        so_far, jobs = delegations_so_far(state), []
        for call in calls:
            spec = BY_TOOL[call.name]
            brief = _brief(call, spec.field)
            if brief is None:
                out[call.id] = Delegated(_error(
                    "invalid_arguments", f"Give the specialist a non-empty '{spec.field}'. "
                                         "Nothing was asked."))
            elif spent:
                out[call.id] = Delegated(_error(
                    "budget_exhausted", f"The run's budget is spent ({spent}), so no more "
                                        "specialists can be asked. Reply with what you know."))
            elif so_far + len(jobs) >= MAX_DELEGATIONS:
                out[call.id] = Delegated(_error(
                    "delegation_limit", f"At most {MAX_DELEGATIONS} specialist questions per "
                                        "ticket. Reply with what you know, or escalate."))
            else:
                jobs.append((call, spec, brief))
        if not jobs:
            return out

        seed = pool_seed(state, ctx, len(jobs))
        lock = threading.Lock()
        # Copies and buffers are made here, in the main thread, which owns the connection.
        prepared = [(call, spec, brief, store_copy(ctx.conn, lock), tracer.child(spec.name))
                    for call, spec, brief in jobs]
        with ContextThreadPoolExecutor(max_workers=max_workers or len(prepared)) as pool:
            futures = [pool.submit(_timed, _run_specialist, spec, call, brief, ctx, conn,
                                   child, seed)
                       for call, spec, brief, conn, child in prepared]
            done = [f.result() for f in futures]

        offset, failure = state["model_calls"], None
        for (call, spec, brief, conn, child), (kind, value, started, ms) in zip(prepared, done):
            conn.close()
            calls_made = sum(1 for line in child.lines if line["type"] == "model_response")
            with tracer.as_agent(spec.name):
                tracer.event("agent_start", call_id=call.id, brief=brief,
                             first_call_index=offset + 1, batch=len(prepared),
                             after_call_index=state["model_calls"], started=started)
                tracer.merge(child, offset)
                if kind == "ok":
                    report = _report(value)
                    out[call.id] = _delta(value, seed, report, spec.name)
                    tracer.event("agent_end", call_id=call.id, status=report["status"],
                                 model_calls=value["model_calls"],
                                 tool_calls=value["tool_calls"],
                                 usage=dict(out[call.id].usage),
                                 cost_usd=out[call.id].cost_usd, latency_ms=ms,
                                 report=report["report"])
                else:
                    tracer.event("agent_error", call_id=call.id, latency_ms=ms,
                                 error=type(value).__name__, message=str(value))
                    failure = failure or value
            offset += calls_made
        if failure is not None:   # an API failure makes an error trial, as in every strategy
            raise failure
        return out

    return run_delegates


# --- The run ---------------------------------------------------------------------------------

def supervisor_fields(guards, *, specialists=SPECIALISTS, max_workers: int | None = None) -> dict:
    return {"agent": "supervisor", "tools": WRITES + ESCALATE,
            "system": supervisor_system(guards),
            "delegates": tuple(s.tool for s in specialists),
            "run_delegates": make_delegate_runner(max_workers)}


def run_supervisor(ticket: str, *, guards=MULTI_GUARDS, strategy: str = STRATEGY,
                   specialists=SPECIALISTS, max_workers: int | None = None, **kwargs):
    """Run one ticket through the supervisor. Takes run_graph_agent's arguments (adapter,
    conn, tracer, chat, policy, reviewer, checkpointer, ...)."""
    return run_graph_agent(ticket, guards=guards, strategy=strategy,
                           agent_fields=supervisor_fields(guards, specialists=specialists,
                                                          max_workers=max_workers),
                           **kwargs)
