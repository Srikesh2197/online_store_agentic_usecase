"""A workflow: classify the ticket, route it, run a fixed chain for its category, and
escalate what does not fit. Routing and prompt chaining, set against the agent of
graph_agent.py, on the same tools, guardrails, tracer and graders.

    START -> route +-> policy_question -----------------------------------------> reply
                   +-> every other intent -> gather -(email, no order id)-> pick -+
                                                    |                             |
                                                    +<----------------------------+
                                                    +-> status ---------------------> reply
                                                    +-> cancel, address_change,
                                                    |   refund_return -> decide -> act ------> reply
                                                    |                          +-> escalate -> reply   (a write on a tainted run)
                                                    |                          +-------------> reply   (no action: refuse or answer)
                                                    +-> complaint, other_request,
                                                        unclear --------------> escalate -----> reply
    reply -> finish -> END

The model does bounded jobs: name the intent (route), choose an order when only an email is
given (pick), choose the actions its intent allows with only those tools bound (decide), and
write the reply with no tools bound. Code does the rest: which lookups run and in what order,
running the chosen actions, and every escalation. A run makes at most four model calls (one
more if a truncated response is retried), so there is no loop to cap or detect.

The guardrails sit where the structure puts them: taint is state (OR-ed) and a write decided
on a tainted run is routed to a person by an edge; an action may only name an order that a
lookup returned (grounding); faults are retried with idempotency keys from the decide call's
ids; the invariants are in the tools; the budget is checked before each model call.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict
from operator import add, or_
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from arl.env.faults import ToolFault
from arl.env.tools import _BY_NAME, execute_tool, tool_specs
from arl.foundations.hand_loop import EXITS
from arl.foundations.single_round import MAX_OUTPUT_TOKENS, Echo, RunResult, build_instructions
from arl.framework.graph_agent import add_counts, union
from arl.framework.models import (
    ChatSetup,
    bind,
    make_chat_model,
    refusal_detail,
    stop_of,
    tool_calls_of,
    traced_call,
)
from arl.guardrails import ALL, Guards
from arl.guardrails.permissions import Taint
from arl.guardrails.prompt import DEFENCE
from arl.guardrails.retry import gave_up, with_retries
from arl.guardrails.validation import Grounding, order_ids
from arl.llm.types import Usage
from arl.tracing.tracer import Tracer

STRATEGY = "workflow"
MAX_MODEL_CALLS = 4 + 1   # route, pick, decide, reply, and one truncation retry
MAX_ORDERS = 3            # lookups per ticket

Intent = Literal["status", "policy_question", "cancel", "address_change", "refund_return",
                 "complaint", "other_request", "unclear"]

# The tools the decide step may call, per intent. Nothing else is bound.
ACTIONS = {
    "cancel": ["cancel_order", "escalate_to_human"],
    "address_change": ["update_shipping_address", "escalate_to_human"],
    "refund_return": ["issue_refund", "create_return", "escalate_to_human"],
}
# Intents escalated by code, and the category they are filed under.
ESCALATED = {"complaint": "complaint", "other_request": "policy_exception",
             "unclear": "cannot_verify"}
WITHOUT_SHIPMENT = {"cancel", "address_change"}   # the other intents look up the shipment too


class Route(BaseModel):
    intent: Intent = Field(description="What the customer wants; see the list in your step")
    order_ids: list[str] = Field(description="Order IDs given in the ticket, e.g. ORD-1001, "
                                             "copied exactly; empty if none")
    email: str | None = Field(description="The customer's email address if given, else null")
    summary: str = Field(description="What the customer wants, in one sentence, for a colleague")


class Pick(BaseModel):
    order_ids: list[str] = Field(description="The IDs of the listed orders the ticket is about; "
                                             "empty if none fits")


ROUTE_STEP = """

## Your step: triage
You are the first step of a fixed process. Do not answer the customer. Classify the ticket:
- status: where an order is, whether it has shipped, when it will arrive.
- policy_question: a general question about the policy, about no particular order.
- cancel: cancel an order.
- address_change: change where an order is delivered.
- refund_return: a refund or a return of items in an order, for any reason.
- complaint: the customer asks for a person.
- other_request: anything else the customer asks for that the tools cannot do, such as a credit or compensation.
- unclear: you cannot tell what the customer wants."""

PICK_STEP = """

## Your step: choose the order
The customer gave no order ID. Their recent orders are listed below. Choose the order or orders the ticket is about. Choose none if no order fits."""

DECIDE_STEP = """

## Your step: decide
The orders the ticket is about have been looked up; the results are below. Following the policy, take the action it allows by calling the tool, with exact amounts and items. If the policy does not allow the request, or a detail is missing, call no tool and say why in one sentence. If the request is outside the rules, escalate. Take only the actions this ticket needs."""

REPLY_STEP = """

## Your step: reply
Write the reply to the customer now. The lookups and any actions taken are below: say only what they confirm. If an action was not taken, do not say or imply that it was; say what will happen next instead. Do not write tool calls."""


# --- State -------------------------------------------------------------------------------

class WorkflowState(TypedDict):
    ticket: str
    route: dict | None
    lookups: Annotated[list[dict], add]       # {"tool", "arguments", "result"}, in order
    grounded: Annotated[list[str], union]     # order ids a lookup returned
    customer_id: str | None
    tainted: Annotated[bool, or_]
    picked: bool
    decision: list[dict]                      # the decide step's calls
    decision_text: str
    actions: Annotated[list[dict], add]       # what act and escalate did
    model_calls: Annotated[int, add]
    tool_calls: Annotated[int, add]
    usage: Annotated[dict[str, int], add_counts]
    cost_usd: Annotated[float, add]
    truncation_retried: bool
    cap_status: str | None
    stop: str | None
    reply: str
    exit: str | None


def initial_state(ticket: str) -> WorkflowState:
    return WorkflowState(ticket=ticket, route=None, lookups=[], grounded=[], customer_id=None,
                         tainted=False, picked=False, decision=[], decision_text="",
                         actions=[], model_calls=0, tool_calls=0, usage={}, cost_usd=0.0,
                         truncation_retried=False, cap_status=None, stop=None, reply="",
                         exit=None)


def case_file(state: WorkflowState) -> HumanMessage:
    """What the later steps are told: the lookups and actions so far, as the tools returned
    them."""
    record = {"lookups": state["lookups"]}
    if state["decision_text"]:
        record["decision"] = state["decision_text"]
    if state["actions"]:
        record["actions"] = state["actions"]
    return HumanMessage("Case file (tool results, as JSON):\n" + json.dumps(record, indent=1))


# --- The graph ---------------------------------------------------------------------------

def build_workflow(*, setup: ChatSetup, conn, tracer: Tracer, guards: Guards, echo: Echo,
                   clock: Callable[[], float], sleep: Callable[[float], None], started: float):
    base = build_instructions() + (DEFENCE if guards.prompt else "")
    specs = {spec.name: spec for spec in tool_specs()}
    sequence = iter(range(1, 1_000))

    # A model call, with the one truncation retry of the run.
    def model_step(state: WorkflowState, runnable_for, messages, step: str,
                   tool_choice: str) -> tuple[object, AIMessage, dict]:
        system = base + step
        index = state["model_calls"] + 1
        output, response, usage, cost = traced_call(
            runnable_for(setup), messages, setup=setup, system=system, tool_choice=tool_choice,
            max_tokens=MAX_OUTPUT_TOKENS, index=index, tracer=tracer, echo=echo)
        update = {"model_calls": 1, "usage": asdict(usage), "cost_usd": cost}
        if (stop_of(response, setup.provider)[0] == "max_tokens" and guards.truncation_retry
                and not state["truncation_retried"]):
            tracer.event("truncation_retry", max_tokens=2 * MAX_OUTPUT_TOKENS)
            output, response, retry_usage, retry_cost = traced_call(
                runnable_for(setup.with_max_tokens(2 * MAX_OUTPUT_TOKENS)), messages,
                setup=setup, system=system, tool_choice=tool_choice,
                max_tokens=2 * MAX_OUTPUT_TOKENS, index=index + 1, tracer=tracer, echo=echo)
            update = {"model_calls": 2, "usage": asdict(usage + retry_usage),
                      "cost_usd": cost + retry_cost, "truncation_retried": True}
        return output, response, update

    # A tool run by code: traced like the agent's calls, with retries and an idempotency key.
    def run_tool(name: str, arguments: str, call_id: str | None = None) -> dict:
        call_id = call_id or f"wf_{next(sequence)}"
        tool = _BY_NAME[name]
        key = (f"{tracer.run_id}:{call_id}"
               if guards.idempotency and tool.kind != "read" else None)

        def attempt() -> dict:
            return execute_tool(conn, name, arguments, idempotency_key=key)

        with tracer.tool_call(call_id=call_id, name=name, arguments=arguments) as record:
            try:
                if guards.retries:
                    result = with_retries(
                        attempt, sleep=sleep,
                        on_retry=lambda n, exc: tracer.event("tool_retry", tool=name,
                                                             call_id=call_id, attempt=n,
                                                             fault=type(exc).__name__, key=key))
                else:
                    result = attempt()
            except ToolFault as exc:
                result = gave_up(name, tool.kind, exc)
            except Exception as exc:  # noqa: BLE001 -- as in the loops: reported, not fatal
                result = {"error": "tool_failed",
                          "message": f"The tool failed: {type(exc).__name__}."}
            record.finish(result=result)
        echo(f"TOOL {name}({arguments})", result)
        return result

    def lookup(name: str, **args) -> tuple[dict, dict]:
        """A read, and the state it adds: the record, grounded ids, taint, customer."""
        arguments = json.dumps(args)
        result = run_tool(name, arguments)
        update: dict = {"lookups": [{"tool": name, "arguments": args, "result": result}],
                        "tool_calls": 1}
        if "error" not in result:
            update["grounded"] = sorted(order_ids(result))
            taint = Taint()
            if guards.taint and taint.observe(name, result):
                tracer.event("guard", layer="taint", tool=name, action="tainted",
                             sources=taint.sources)
                update["tainted"] = True
            if name == "get_order":
                update["customer_id"] = result["order"]["customer_id"]
        return result, update

    def merge(total: dict, update: dict) -> dict:
        for key, value in update.items():
            if key in ("lookups",):
                total[key] = total.get(key, []) + value
            elif key == "grounded":
                total[key] = union(total.get(key, []), value)
            elif key == "tool_calls":
                total[key] = total.get(key, 0) + value
            else:
                total[key] = value
        return total

    def look_up_orders(intent: str, ids: list[str]) -> dict:
        total: dict = {}
        for order_id in ids[:MAX_ORDERS]:
            merge(total, lookup("get_order", order_id=order_id)[1])
            if intent not in WITHOUT_SHIPMENT:
                merge(total, lookup("get_shipment", order_id=order_id)[1])
        return total

    def over_budget(state: WorkflowState) -> str | None:
        if not guards.limits:
            return None
        usage = state["usage"]
        return guards.limits.tripped(
            tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            usd=state["cost_usd"], seconds=clock() - started)

    # --- Nodes ---

    def structured(state: WorkflowState, schema, messages, step: str) -> tuple[object, dict]:
        """A structured-output step. ChatOpenAI parses the answer inside the model call, so an
        unreadable answer raises there, before its usage reaches us: it is logged as an event
        and treated as no answer, and that call's tokens are missing from the trace."""
        try:
            output, _, update = model_step(
                state, lambda s: s.chat.with_structured_output(schema, include_raw=True),
                messages, step, f"structured: {schema.__name__}")
        except Exception as exc:  # noqa: BLE001 -- the run goes on to a person
            tracer.event("structured_output_error", schema=schema.__name__,
                         error=f"{type(exc).__name__}: {str(exc)[:300]}")
            return None, {"model_calls": 1}
        return (output.get("parsed") if isinstance(output, dict) else None), update

    def route(state: WorkflowState) -> dict:
        parsed, update = structured(state, Route, [HumanMessage(state["ticket"])], ROUTE_STEP)
        if parsed is None:   # a refusal or an unreadable answer: a person decides
            parsed = Route(intent="unclear", order_ids=[], email=None,
                           summary="The ticket could not be classified.")
        parsed.order_ids = [i.strip().upper() for i in parsed.order_ids]
        tracer.event("route", intent=parsed.intent, order_ids=parsed.order_ids,
                     email=parsed.email)
        return update | {"route": parsed.model_dump()}

    def gather(state: WorkflowState) -> dict:
        intent, ids, email = (state["route"]["intent"], state["route"]["order_ids"],
                              state["route"]["email"])
        if ids:
            return look_up_orders(intent, ids)
        if not email:
            return {}
        total: dict = {}
        customer, update = lookup("find_customer", email=email)
        merge(total, update)
        if "error" not in customer:
            customer_id = customer["customer"]["id"]
            total["customer_id"] = customer_id
            merge(total, lookup("list_orders", customer_id=customer_id, limit=None)[1])
        return total

    def needs_pick(state: WorkflowState) -> bool:
        return (not state["route"]["order_ids"] and not state["picked"]
                and any(r["tool"] == "list_orders" and "error" not in r["result"]
                        for r in state["lookups"]))

    def pick(state: WorkflowState) -> dict:
        parsed, update = structured(state, Pick, [HumanMessage(state["ticket"]),
                                                  case_file(state)], PICK_STEP)
        listed = {o["id"] for r in state["lookups"] if r["tool"] == "list_orders"
                  for o in r["result"].get("orders", [])}
        chosen = [i.strip().upper() for i in (parsed.order_ids if parsed else [])]
        chosen = [i for i in chosen if i in listed]   # only orders the lookup returned
        tracer.event("pick", order_ids=chosen)
        return update | {"picked": True} | look_up_orders(state["route"]["intent"], chosen)

    def decide(state: WorkflowState) -> dict:
        allowed = [specs[name] for name in ACTIONS[state["route"]["intent"]]]
        _, response, update = model_step(
            state, lambda s: bind(s, allowed, "auto"),
            [HumanMessage(state["ticket"]), case_file(state)], DECIDE_STEP, "auto")
        stop = stop_of(response, setup.provider)[0]
        calls = tool_calls_of(response) if stop == "tool_calls" else []
        names = {spec.name for spec in allowed}
        decision = [{"id": c.id, "name": c.name, "arguments": c.arguments}
                    for c in calls if c.name in names]
        return update | {"decision": decision, "decision_text": response.text}

    def act(state: WorkflowState) -> dict:
        grounding = Grounding()
        grounding.seen = set(state["grounded"])
        actions = []
        for call in state["decision"]:
            blocked = grounding.check(call["name"], call["arguments"])
            if blocked:
                tracer.event("guard", layer="validation", tool=call["name"],
                             call_id=call["id"], action=blocked["error"])
                with tracer.tool_call(call_id=call["id"], name=call["name"],
                                      arguments=call["arguments"]) as record:
                    record.finish(result=blocked)
                result = blocked
            else:
                result = run_tool(call["name"], call["arguments"], call_id=call["id"])
            actions.append({"tool": call["name"], "arguments": json.loads(call["arguments"]),
                            "result": result})
        return {"actions": actions, "tool_calls": len(actions)}

    def escalate(state: WorkflowState) -> dict:
        intent, routed = state["route"]["intent"], state["route"]
        summary = routed["summary"]
        if intent in ESCALATED:
            category = ESCALATED[intent]
        else:   # a write decided on a run that has read untrusted text
            category = "other"
            tracer.event("guard", layer="taint", action="routed_to_person",
                         tools=[c["name"] for c in state["decision"]])
            summary += (" The order has notes written by third parties, so the change the "
                        "customer asked for needs a person to check and make it.")
        order_id = next((i for i in routed["order_ids"] if i in state["grounded"]),
                        state["grounded"][0] if state["grounded"] else None)
        args = {"category": category, "summary": summary[:1500], "order_id": order_id,
                "customer_id": state["customer_id"]}
        result = run_tool("escalate_to_human", json.dumps(args))
        return {"actions": [{"tool": "escalate_to_human", "arguments": args, "result": result}],
                "tool_calls": 1}

    def reply(state: WorkflowState) -> dict:
        update: dict = {}
        if reason := over_budget(state):
            usage = state["usage"]
            tracer.event("limit", reason=reason, steps=state["model_calls"],
                         tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                         cost_usd=state["cost_usd"])
            update["cap_status"] = reason
        _, response, call_update = model_step(
            state, lambda s: s.chat, [HumanMessage(state["ticket"]), case_file(state)],
            REPLY_STEP, "none (no tools bound)")
        stop = stop_of(response, setup.provider)[0]
        exit_ = EXITS.get(stop, "stopped")
        if exit_ == "completed" and not response.text:
            exit_ = "no_reply"
        if update.get("cap_status") and exit_ == "completed":
            exit_ = update["cap_status"]
        tracer.event("loop_exit", exit=exit_, steps=state["model_calls"] + call_update[
                         "model_calls"], provider_stop=stop_of(response, setup.provider)[1],
                     detail=refusal_detail(response, setup.provider))
        return update | call_update | {"stop": stop, "reply": response.text, "exit": exit_}

    # --- Edges ---

    def after_route(state: WorkflowState) -> str:
        if over_budget(state) or state["route"]["intent"] == "policy_question":
            return "reply"
        return "gather"

    def after_lookups(state: WorkflowState) -> str:
        intent = state["route"]["intent"]
        if over_budget(state):
            return "reply"
        if needs_pick(state):
            return "pick"
        if intent in ESCALATED:
            return "escalate"
        if intent in ACTIONS:
            return "decide"
        return "reply"

    def after_decide(state: WorkflowState) -> str:
        if not state["decision"]:
            return "reply"            # no action: a refusal, or a detail is missing
        writes = [c for c in state["decision"] if _BY_NAME[c["name"]].kind == "write"]
        if writes and guards.taint and state["tainted"]:
            return "escalate"         # Rule of Two: no write after untrusted text
        return "act"

    graph = StateGraph(WorkflowState)
    for name, node in [("route", route), ("gather", gather), ("pick", pick),
                       ("decide", decide), ("act", act), ("escalate", escalate),
                       ("reply", reply)]:
        graph.add_node(name, node)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["gather", "reply"])
    graph.add_conditional_edges("gather", after_lookups,
                                ["pick", "escalate", "decide", "reply"])
    graph.add_conditional_edges("pick", after_lookups, ["escalate", "decide", "reply"])
    graph.add_conditional_edges("decide", after_decide, ["act", "escalate", "reply"])
    graph.add_edge("act", "reply")
    graph.add_edge("escalate", "reply")
    graph.add_edge("reply", END)
    return graph.compile()


def run_workflow(
    ticket: str,
    *,
    ticket_id: str,
    conn,
    adapter,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
    guards: Guards = ALL,
    chat: ChatSetup | None = None,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    setup = chat or make_chat_model(adapter.model)
    started = clock()
    graph = build_workflow(setup=setup, conn=conn, tracer=tracer, guards=guards, echo=echo,
                           clock=clock, sleep=sleep, started=started)
    with tracer.run(ticket_id=ticket_id, ticket=ticket, model=setup.model,
                    provider=setup.provider, strategy=STRATEGY):
        state = graph.invoke(initial_state(ticket),
                             {"callbacks": tracer.langchain_callbacks()})
        usage = Usage(**state["usage"])
        result = RunResult(status=state["exit"], reply=state["reply"], stop=state["stop"],
                           model_calls=state["model_calls"], tool_calls=state["tool_calls"],
                           usage=usage, cost_usd=state["cost_usd"],
                           latency_ms=round((clock() - started) * 1000))
        tracer.end_run(status=result.status, reply=result.reply, stop=result.stop,
                       model_calls=result.model_calls, tool_calls=result.tool_calls,
                       usage=usage, cost_usd=result.cost_usd, latency_ms=result.latency_ms)
    return result
