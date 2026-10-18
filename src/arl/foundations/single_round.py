"""Ladder rung 1: a single round of tool use, against the OpenAI Responses API.

    request 1  ->  the model answers, or asks for tools
    run tools  ->  our code runs them (the model cannot)
    request 2  ->  the model writes the reply from the results

There is no loop. Whatever the model did not ask for in request 1, it never gets.

Requests are built as plain dicts and responses are read as plain dicts, so what is
printed and logged is the JSON that went over the wire.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

from arl.env.seed import SIM_TODAY
from arl.env.tools import execute_tool, tool_schemas
from arl.tracing.cost import Usage, cost_usd, price_for
from arl.tracing.tracer import Tracer

STRATEGY = "single_round"
MAX_OUTPUT_TOKENS = 2000

# send(request) -> (response body, provider request id)
Send = Callable[[dict], tuple[dict, str | None]]
Echo = Callable[[str, object], None]


@dataclass(frozen=True)
class RunResult:
    status: str        # "completed", or "no_reply" if the run ended without reply text
    reply: str
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


def openai_sender(client) -> Send:
    """Send a request with the OpenAI SDK and return the response body as received."""

    def send(request: dict) -> tuple[dict, str | None]:
        raw = client.responses.with_raw_response.create(**request)
        return json.loads(raw.text), raw.headers.get("x-request-id")

    return send


def usage_from_openai(body: dict) -> Usage:
    usage = body.get("usage") or {}
    return Usage(
        input_tokens=usage.get("input_tokens", 0),
        cached_input_tokens=(usage.get("input_tokens_details") or {}).get("cached_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
    )


def output_text(body: dict) -> str:
    """The reply text: every `output_text` part of every `message` item."""
    return "".join(
        part["text"]
        for item in body.get("output", [])
        if item["type"] == "message"
        for part in item["content"]
        if part["type"] == "output_text"
    )


def run_single_round(
    ticket: str,
    *,
    ticket_id: str,
    conn: sqlite3.Connection,
    send: Send,
    model: str,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
) -> RunResult:
    price = price_for(model)
    usage, cost, model_calls = Usage(), 0.0, 0
    started = time.perf_counter()

    def call_model(request: dict) -> dict:
        nonlocal usage, cost, model_calls
        model_calls += 1
        echo(f"REQUEST {model_calls}", request)
        with tracer.model_call(model_calls, request) as record:
            body, request_id = send(request)
            call_usage = usage_from_openai(body)
            call_cost = cost_usd(call_usage, price)
            record.finish(response=body, usage=call_usage, cost_usd=call_cost,
                          request_id=request_id)
        usage, cost = usage + call_usage, cost + call_cost
        echo(f"RESPONSE {model_calls}", body)
        return body

    with tracer.run(ticket_id=ticket_id, ticket=ticket, model=model, strategy=STRATEGY):
        request = {
            "model": model,
            "instructions": build_instructions(),
            "input": [{"role": "user", "content": ticket}],
            "tools": tool_schemas(),
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            # Stateless: OpenAI keeps nothing, so request 2 must carry the whole conversation.
            "store": False,
            # Reasoning items come back encrypted so they can be returned in request 2.
            "include": ["reasoning.encrypted_content"],
        }
        body = call_model(request)
        calls = [item for item in body["output"] if item["type"] == "function_call"]

        if calls:
            results = []
            for call in calls:
                with tracer.tool_call(
                    call_id=call["call_id"], name=call["name"], arguments=call["arguments"]
                ) as record:
                    result = execute_tool(conn, call["name"], call["arguments"])
                    record.finish(result=result)
                echo(f"TOOL {call['name']}({call['arguments']})", result)
                results.append({
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": json.dumps(result),
                })
            # The model's own output items go back verbatim, followed by one result per call.
            # tool_choice "none" forbids further calls, so this response must be the reply.
            request = {
                **request,
                "input": request["input"] + body["output"] + results,
                "tool_choice": "none",
            }
            body = call_model(request)

        reply = output_text(body)
        result = RunResult(
            status="completed" if reply else "no_reply",
            reply=reply,
            model_calls=model_calls,
            tool_calls=len(calls),
            usage=usage,
            cost_usd=cost,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        tracer.end_run(
            status=result.status, reply=reply, model_calls=model_calls, tool_calls=len(calls),
            usage=usage, cost_usd=cost, latency_ms=result.latency_ms,
        )
    return result
