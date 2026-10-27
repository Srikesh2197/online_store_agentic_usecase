"""Ladder rung 2: a hand-written agent loop, against either provider.

    call the model  ->  it answers, or asks for tools
    run the tools   ->  every call gets exactly one result, errors included
    send it all back, and repeat until the model stops on its own

The model is stateless, so each request carries the whole conversation: the ticket, every
assistant turn replayed natively (reasoning included), and every batch of results.

What ends the loop is the neutral stop reason of the latest response:

    tool_calls   run the calls and go round again
    end          the reply is this response's text
    max_tokens   truncated: stop, and do not run any call in it (its arguments may be cut)
    refusal      stop
    other        stop

The only safety net is a step cap on model calls. The last call is reserved for the
reply: when the cap is reached, tools are switched off and the model is told to say
honestly what it could not do (the same closing instruction as rung 1).
"""

import json
import sqlite3
import time

from arl.env.tools import execute_tool, tool_specs
from arl.foundations.single_round import (
    CLOSING_INSTRUCTION,
    MAX_OUTPUT_TOKENS,
    Echo,
    RunResult,
    build_instructions,
)
from arl.llm.pricing import cost_usd, price_for
from arl.llm.types import (
    Adapter,
    Message,
    ModelResponse,
    Text,
    ToolCall,
    ToolChoice,
    ToolResult,
    Usage,
)
from arl.tracing.tracer import Tracer

STRATEGY = "hand_loop"
MAX_STEPS = 10   # model calls per run, the reply call included

# How the run ended, by the stop reason of the last response.
EXITS = {"end": "completed", "max_tokens": "truncated", "refusal": "refused", "other": "stopped"}


def refusal_detail(response: ModelResponse) -> str | None:
    """What the provider said about a refusal, for the log."""
    if response.stop != "refusal":
        return None
    if response.provider == "anthropic":
        return json.dumps(response.raw.get("stop_details"))
    return " ".join(
        content.get("refusal", "")
        for item in response.raw.get("output", []) if item["type"] == "message"
        for content in item["content"] if content["type"] == "refusal"
    ) or response.provider_stop


def run_hand_loop(
    ticket: str,
    *,
    ticket_id: str,
    conn: sqlite3.Connection,
    adapter: Adapter,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
    max_steps: int = MAX_STEPS,
) -> RunResult:
    if max_steps < 2:
        raise ValueError("max_steps must be at least 2: one call to act, one to reply.")
    price = price_for(adapter.model)
    system, tools = build_instructions(), tool_specs()
    usage, cost, model_calls, tool_calls = Usage(), 0.0, 0, 0
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

    def run_tool(call: ToolCall) -> ToolResult:
        nonlocal tool_calls
        tool_calls += 1
        with tracer.tool_call(call_id=call.id, name=call.name, arguments=call.arguments) as record:
            try:
                result = execute_tool(conn, call.name, call.arguments)
            except Exception as exc:  # noqa: BLE001 -- a broken tool is reported, not fatal
                result = {"error": "tool_failed",
                          "message": f"The tool failed: {type(exc).__name__}. Nothing was changed."}
            record.finish(result=result)
        echo(f"TOOL {call.name}({call.arguments})", result)
        return ToolResult(call.id, json.dumps(result), is_error="error" in result)

    with tracer.run(ticket_id=ticket_id, ticket=ticket, model=adapter.model,
                    provider=adapter.provider, strategy=STRATEGY):
        messages = [Message("user", [Text(ticket)])]
        for step in range(1, max_steps + 1):
            capped = step == max_steps
            if capped:
                # The cap is reached and the model still wants tools. Its last calls have run;
                # this call may only reply, and is told so after the results.
                tracer.event("step_cap", max_steps=max_steps)
                results = messages.pop()
                messages.append(Message("user", [*results.parts, Text(CLOSING_INSTRUCTION)]))
            response = call_model(messages, "none" if capped else "auto")
            if response.stop == "tool_calls" and not capped:
                # Every call in the batch runs, in order, before the model sees any result.
                results = [run_tool(call) for call in response.tool_calls]
                messages += [response.message(), Message("user", results)]
                continue
            break

        exit_ = EXITS.get(response.stop, "stopped")   # tool_calls under tool_choice none: stopped
        if exit_ == "completed" and not response.text:
            exit_ = "no_reply"
        if capped and exit_ == "completed":
            exit_ = "step_cap"
        tracer.event("loop_exit", exit=exit_, steps=model_calls,
                     provider_stop=response.provider_stop, detail=refusal_detail(response))
        result = RunResult(
            status=exit_,
            reply=response.text,
            stop=response.stop,
            model_calls=model_calls,
            tool_calls=tool_calls,
            usage=usage,
            cost_usd=cost,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        tracer.end_run(
            status=exit_, reply=response.text, stop=response.stop, model_calls=model_calls,
            tool_calls=tool_calls, usage=usage, cost_usd=cost, latency_ms=result.latency_ms,
        )
    return result
