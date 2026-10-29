"""Handoffs: peers take turns on one shared conversation (Stage 8, rung 4).

There is no agent above the others. One state holds the conversation, and `active` names
the peer whose turn it is. A peer hands the ticket on with a transfer tool. The call is
answered with a ToolMessage, as every call must be, and `active` changes, so the next
model call is made by the new peer with its own prompt and tools, over the same messages.
This is the "a tool updates the active agent, routing reads it" form of handoffs in the
LangChain docs, written as one graph:

    START -> model(active peer) --tool calls--> tools -> limits -> model(active peer) ...
                                 --otherwise--> finish -> END

    triage    no lookups; hands the ticket to orders or actions (or answers a pure question
              about the rules itself)
    orders    lookups; answers questions; hands to actions when something must change
    actions   lookups, the writes and escalation: the single writer

The nodes are graph_agent.py's own, called with the active peer's context
(`runtime.override(context=...)`). Everything else is the run's, shared by the peers: the
messages, the step cap, the budget pool, taint, grounded ids and loop counts.

What is shared, lost and duplicated: every peer sees the whole conversation (the ticket,
every earlier peer's calls, results and reasoning); a peer loses only the earlier peer's
instructions, learning why it has the ticket from the transfer's `reason`; and every call
resends the whole history under the active peer's prompt, plus one extra turn per handoff.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from operator import add
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from arl.foundations.hand_loop import MAX_STEPS
from arl.foundations.single_round import Echo, RunResult
from arl.framework import graph_agent as ga
from arl.framework.graph_agent import AgentContext, AgentState, Delegated
from arl.framework.models import make_chat_model
from arl.framework.multi.specialists import (
    ESCALATE,
    MULTI_GUARDS,
    READS,
    WRITES,
    prompt,
    text_tool,
)
from arl.guardrails import Guards
from arl.tracing.tracer import Tracer

STRATEGY = "handoffs"
MAX_HANDOFFS = 3          # per ticket
FIRST = "triage"


class HandoffState(AgentState):
    active: str                          # the peer whose turn it is
    handoffs: Annotated[int, add]


@dataclass(frozen=True)
class Peer:
    name: str
    tools: tuple[str, ...]
    hands_to: tuple[str, ...]
    role: str

    def system(self, guards: Guards) -> str:
        return prompt(guards, self.name, self.role)


def transfer_tool(target: str):
    return text_tool(f"transfer_to_{target}",
                     f"Hand this conversation to the {target} agent. It sees everything said "
                     "so far and continues from here; you stop. Make this the only call in "
                     "your turn.",
                     "reason", "Why it should take over, and what you found that it needs")


TRIAGE = Peer("triage", (), ("orders", "actions"), """
You are the first contact for every ticket. You have no lookup tools and cannot change
anything. Read the ticket and hand it over with one transfer call:
- transfer_to_orders for questions about orders, deliveries, tracking or the rules;
- transfer_to_actions for anything that may need a refund, a return, a cancellation, an
  address change, or a person.
If the ticket is only a general question about the rules, answer it yourself instead.
""")

ORDERS = Peer("orders", READS, ("actions",), """
You answer questions about orders, deliveries and tracking, using your lookup tools. You
cannot change anything. If the customer needs a refund, a return, a cancellation, an address
change or a person, hand the conversation to the actions agent with transfer_to_actions
(say what you found in the reason) and do not reply yourself. Otherwise reply to the customer.
""")

ACTIONS = Peer("actions", READS + WRITES + ESCALATE, (), """
You are the only agent that can change the store: refunds, returns, cancellations, address
changes and escalations. Earlier agents may have looked things up already; their results are
in the conversation. Check what the policy needs before you act, then reply to the customer.
""")

_SHARED = """
You share this conversation with other agents (triage, orders, actions). Earlier assistant
turns, tool calls and results in it may have been made by them, not by you. When a
transfer result says the ticket is yours, it is yours: carry on from there.
"""
TRIAGE, ORDERS, ACTIONS = (replace(p, role=p.role + _SHARED) for p in (TRIAGE, ORDERS, ACTIONS))
PEERS = {p.name: p for p in (TRIAGE, ORDERS, ACTIONS)}


# --- Handing over ------------------------------------------------------------------------------

def _reason(call) -> str | None:
    try:
        value = json.loads(call.arguments).get("reason")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def handed_over(target: str, source: str | None, reason: str) -> str:
    """The transfer's result. The next peer reads it as the newest message of a
    conversation whose earlier assistant turns it did not write, so it says plainly who
    has the ticket now (the smoke run showed a peer taking the transfer for its own and
    replying with nothing)."""
    return (f"You are now the {target} agent, and this ticket is yours. The {source} agent "
            f"handed it to you because: {reason} Do what the customer needs with your own "
            "tools, then reply to the customer yourself.")


def run_transfers(calls, state, ctx) -> dict[str, Delegated]:
    """The `run_delegates` of every peer: at most one handoff per turn, and per ticket at
    most MAX_HANDOFFS. The handoff itself is a state change (`active`), applied when the
    step ends, so any other calls of the turn still run as the peer that made them."""
    out, handed = {}, False
    for call in calls:
        target = call.name.removeprefix("transfer_to_")
        reason = _reason(call)
        if handed:
            out[call.id] = Delegated({"error": "one_handoff_per_turn",
                                      "message": "This turn already hands the conversation "
                                                 "over. Nothing else was transferred."})
        elif state["handoffs"] >= MAX_HANDOFFS:
            out[call.id] = Delegated({"error": "handoff_limit",
                                      "message": f"The ticket has been handed over "
                                                 f"{MAX_HANDOFFS} times. Do not transfer "
                                                 "again: reply, or escalate if you can."})
        elif reason is None:
            out[call.id] = Delegated({"error": "invalid_arguments",
                                      "message": "Give a non-empty 'reason'. Nothing was "
                                                 "transferred."})
        else:
            handed = True
            ctx.tracer.event("handoff", call_id=call.id, to=target, reason=reason,
                             after_call_index=state["model_calls"])
            out[call.id] = Delegated(
                {"transferred_to": target, "message": handed_over(target, ctx.agent, reason)},
                update={"active": target, "handoffs": 1})
    return out


def peer_context(ctx: AgentContext, active: str) -> AgentContext:
    peer = PEERS[active]
    return replace(ctx, agent=peer.name, tools=peer.tools, system=peer.system(ctx.guards),
                   delegates=tuple(transfer_tool(t) for t in peer.hands_to),
                   run_delegates=run_transfers)


# --- The graph: graph_agent's nodes, run as the active peer ----------------------------------------

def _as_peer(node: Callable) -> Callable:
    def run(state: HandoffState, runtime: Runtime[AgentContext]) -> dict:
        ctx = peer_context(runtime.context, state["active"])
        with ctx.tracer.as_agent(ctx.agent):
            return node(state, runtime.override(context=ctx))
    run.__name__ = node.__name__
    return run


@lru_cache(maxsize=8)
def handoff_graph(checkpointer=None):
    graph = StateGraph(HandoffState, context_schema=AgentContext)
    graph.add_node("model", _as_peer(ga.model))
    graph.add_node("tools", _as_peer(ga.tools_node))
    graph.add_node("limits", _as_peer(ga.limits))
    graph.add_node("finish", _as_peer(ga.finish))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", ga.after_model, ["tools", "finish"])
    graph.add_edge("tools", "limits")
    graph.add_edge("limits", "model")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def run_handoffs(
    ticket: str,
    *,
    ticket_id: str,
    conn,
    adapter,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
    guards: Guards = MULTI_GUARDS,
    strategy: str = STRATEGY,
    chat=None,
    max_steps: int = MAX_STEPS,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    """Run one ticket through the peers, starting with triage. One step cap, one budget
    pool and one taint flag for the whole conversation, whichever peer is active."""
    setup = chat or make_chat_model(adapter.model)
    started = clock()
    ctx = AgentContext(setup=setup, conn=conn, tracer=tracer, guards=guards,
                       max_steps=max_steps, echo=echo, clock=clock, sleep=sleep,
                       started=started, agent=FIRST)
    state = ga.initial_state(ticket) | {"active": FIRST, "handoffs": 0}
    with tracer.as_agent(FIRST), tracer.run(ticket_id=ticket_id, ticket=ticket,
                                            model=setup.model, provider=setup.provider,
                                            strategy=strategy):
        config = ga.run_config(tracer, max_steps, gated=False, thread_id=None)
        return ga.drive(handoff_graph(), state, config, ctx)
