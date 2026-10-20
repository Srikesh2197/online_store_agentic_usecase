"""Ladder rung 1: a single round of tool use, against either provider.

    request 1  ->  the model answers, or asks for tools
    run tools  ->  our code runs them (the model cannot)
    request 2  ->  the model writes the reply from the results

There is no loop. Whatever the model did not ask for in request 1, it never gets.

The conversation is held as neutral `Message`s. The adapter turns it into the
provider's request body, and that body is what is printed and logged, so what you
see is the JSON that went over the wire.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

from arl.env.seed import SIM_TODAY
from arl.env.tools import execute_tool, tool_specs
from arl.llm.pricing import cost_usd, price_for
from arl.llm.types import Adapter, Message, ModelResponse, Text, ToolChoice, ToolResult, Usage
from arl.tracing.tracer import Tracer

STRATEGY = "single_round"
MAX_OUTPUT_TOKENS = 2000

# Sent after the tool results in request 2. With tool_choice "none" the model cannot act
# any more, but it may still want to; in Phase 1 Haiku 5.5 then wrote tool calls as text or
# claimed actions it had not taken. This tells it the round is over and how to end honestly.
CLOSING_INSTRUCTION = (
    "No more tools can be used for this ticket. Write your reply to the customer now, using "
    "only the results above. Do not write tool calls. If an action is still needed, do not say "
    "or imply that it has been done or is being done; say plainly what you could not do in "
    "this reply and what is still needed."
)

Echo = Callable[[str, object], None]


@dataclass(frozen=True)
class RunResult:
    status: str        # "completed", or "no_reply" if the run ended without reply text
    reply: str
    stop: str          # the neutral stop reason of the last response
    model_calls: int
    tool_calls: int
    usage: Usage
    cost_usd: float
    latency_ms: int


def build_instructions() -> str:
    policy = resources.files("arl.env").joinpath("policy.md").read_text()
    return (
        "You are a customer support assistant for Northwind Outfitters, an online store. "
        "Follow the policy below.\n"
        f"Today's date is {SIM_TODAY.isoformat()}.\n\n{policy}"
    )


def run_single_round(
    ticket: str,
    *,
    ticket_id: str,
    conn: sqlite3.Connection,
    adapter: Adapter,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
) -> RunResult:
    price = price_for(adapter.model)
    system, tools = build_instructions(), tool_specs()
    usage, cost, model_calls = Usage(), 0.0, 0
    started = time.perf_counter()

    def call_model(messages: list[Message], tool_choice: ToolChoice) -> ModelResponse:
        nonlocal usage, cost, model_calls
        model_calls += 1
        request = adapter.build_request(system=system, messages=messages, tools=tools,
                                        tool_choice=tool_choice, max_tokens=MAX_OUTPUT_TOKENS)
        echo(f"REQUEST {model_calls} ({adapter.provider})", request)
        with tracer.model_call(model_calls, request, provider=adapter.provider) as record:
            body, request_id = adapter.send(request)
            response = adapter.parse_response(body)
            call_cost = cost_usd(response.usage, price)
            record.finish(response=body, usage=response.usage, cost_usd=call_cost,
                          request_id=request_id, stop=response.stop,
                          provider_stop=response.provider_stop)
        usage, cost = usage + response.usage, cost + call_cost
        echo(f"RESPONSE {model_calls} (stop: {response.stop} / {response.provider_stop})", body)
        return response

    with tracer.run(ticket_id=ticket_id, ticket=ticket, model=adapter.model,
                    provider=adapter.provider, strategy=STRATEGY):
        messages = [Message("user", [Text(ticket)])]
        response = call_model(messages, "auto")
        calls = response.tool_calls

        if calls:
            results = []
            for call in calls:
                with tracer.tool_call(
                    call_id=call.id, name=call.name, arguments=call.arguments
                ) as record:
                    result = execute_tool(conn, call.name, call.arguments)
                    record.finish(result=result)
                echo(f"TOOL {call.name}({call.arguments})", result)
                results.append(ToolResult(call.id, json.dumps(result), is_error="error" in result))
            # The model's own turn goes back verbatim, then one result per call and the
            # closing instruction. tool_choice "none" forbids further calls, so this response
            # must be the reply.
            messages = messages + [response.message(),
                                   Message("user", [*results, Text(CLOSING_INSTRUCTION)])]
            response = call_model(messages, "none")

        reply = response.text
        result = RunResult(
            status="completed" if reply else "no_reply",
            reply=reply,
            stop=response.stop,
            model_calls=model_calls,
            tool_calls=len(calls),
            usage=usage,
            cost_usd=cost,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        tracer.end_run(
            status=result.status, reply=reply, stop=result.stop, model_calls=model_calls,
            tool_calls=len(calls), usage=usage, cost_usd=cost, latency_ms=result.latency_ms,
        )
    return result
