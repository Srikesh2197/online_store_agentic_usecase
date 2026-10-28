"""Rung 2 with guardrails (Stage 5): the hand-written loop plus switchable layers.

With every layer off this loop sends the same requests and runs the same tools as
hand_loop.py (a test checks it), so an experiment's arms differ only in the layers on:

    before a model call   budgets (tokens, dollars, time); the step cap as before
    before a tool runs    loop detection, taint (no writes after untrusted text), grounding
    running a tool        retries with backoff for faults, an idempotency key on writes
    after a tool ran      taint and grounding observe the result
    a truncated response  one retry with twice the output limit

When a budget trips or a loop is detected, the loop ends the way it ends at the step cap:
one reply-only call with the closing instruction, and a status that names the cause.
"""

import json
import sqlite3
import time
from collections.abc import Callable

from arl.env.faults import ToolFault
from arl.env.tools import _BY_NAME, execute_tool, tool_specs
from arl.foundations.hand_loop import EXITS, MAX_STEPS, refusal_detail
from arl.foundations.single_round import (
    CLOSING_INSTRUCTION,
    MAX_OUTPUT_TOKENS,
    Echo,
    RunResult,
    build_instructions,
)
from arl.guardrails import OFF, Guards
from arl.guardrails.loopdetect import LoopDetector
from arl.guardrails.permissions import Taint
from arl.guardrails.prompt import DEFENCE
from arl.guardrails.retry import gave_up, with_retries
from arl.guardrails.validation import Grounding
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


def run_guarded_loop(
    ticket: str,
    *,
    ticket_id: str,
    conn: sqlite3.Connection,
    adapter: Adapter,
    tracer: Tracer,
    echo: Echo = lambda title, payload: None,
    guards: Guards = OFF,
    max_steps: int = MAX_STEPS,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    if max_steps < 2:
        raise ValueError("max_steps must be at least 2: one call to act, one to reply.")
    price = price_for(adapter.model)
    system = build_instructions() + (DEFENCE if guards.prompt else "")
    tools = tool_specs()
    usage, cost, model_calls, tool_calls = Usage(), 0.0, 0, 0
    started = clock()
    loops = LoopDetector() if guards.loop_detect else None
    taint = Taint() if guards.taint else None
    grounding = Grounding() if guards.validation else None
    truncation_retried = False

    def call_model(messages: list[Message], tool_choice: ToolChoice,
                   max_tokens: int = MAX_OUTPUT_TOKENS) -> ModelResponse:
        nonlocal usage, cost, model_calls
        model_calls += 1
        request = adapter.build_request(system=system, messages=messages, tools=tools,
                                        tool_choice=tool_choice, max_tokens=max_tokens)
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

    def guard(layer: str, call: ToolCall, result: dict) -> dict:
        tracer.event("guard", layer=layer, tool=call.name, call_id=call.id,
                     action=result["error"])
        return result

    def gate(call: ToolCall) -> dict | None:
        """An error result if a guardrail stops this call before it runs."""
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

    def run_tool(call: ToolCall) -> ToolResult:
        nonlocal tool_calls
        tool_calls += 1
        with tracer.tool_call(call_id=call.id, name=call.name, arguments=call.arguments) as record:
            result = gate(call)
            if result is None:
                try:
                    result = execute(call)
                except Exception as exc:  # noqa: BLE001 -- as in hand_loop: reported, not fatal
                    result = {"error": "tool_failed",
                              "message": f"The tool failed: {type(exc).__name__}. "
                                         "Nothing was changed."}
                if "error" not in result:
                    if taint and taint.observe(call.name, result):
                        tracer.event("guard", layer="taint", tool=call.name, call_id=call.id,
                                     action="tainted", sources=taint.sources)
                    if grounding:
                        grounding.observe(call.name, result)
            record.finish(result=result)
        echo(f"TOOL {call.name}({call.arguments})", result)
        return ToolResult(call.id, json.dumps(result), is_error="error" in result)

    def stop_reason() -> str | None:
        """Why the loop must end now with a reply-only call, if it must."""
        if loops and loops.stop:
            return "loop_detected"
        if guards.limits:
            return guards.limits.tripped(tokens=usage.input_tokens + usage.output_tokens,
                                         usd=cost, seconds=clock() - started)
        return None

    with tracer.run(ticket_id=ticket_id, ticket=ticket, model=adapter.model,
                    provider=adapter.provider, strategy=guards.name):
        messages = [Message("user", [Text(ticket)])]
        cap_status = None
        for step in range(1, max_steps + 1):
            reason = stop_reason() if step > 1 else None
            if step == max_steps or reason:
                # As at the step cap: the last calls have run, this call may only reply.
                cap_status = reason or "step_cap"
                if reason:
                    tracer.event("limit", reason=reason, steps=model_calls,
                                 tokens=usage.input_tokens + usage.output_tokens, cost_usd=cost)
                else:
                    tracer.event("step_cap", max_steps=max_steps)
                results = messages.pop()
                messages.append(Message("user", [*results.parts, Text(CLOSING_INSTRUCTION)]))
            capped = cap_status is not None
            response = call_model(messages, "none" if capped else "auto")
            if (response.stop == "max_tokens" and guards.truncation_retry
                    and not truncation_retried):
                truncation_retried = True
                tracer.event("truncation_retry", max_tokens=2 * MAX_OUTPUT_TOKENS)
                response = call_model(messages, "none" if capped else "auto",
                                      max_tokens=2 * MAX_OUTPUT_TOKENS)
            if response.stop == "tool_calls" and not capped:
                results = [run_tool(call) for call in response.tool_calls]
                messages += [response.message(), Message("user", results)]
                if grounding:
                    grounding.end_turn()
                continue
            break

        exit_ = EXITS.get(response.stop, "stopped")
        if exit_ == "completed" and not response.text:
            exit_ = "no_reply"
        if capped and exit_ == "completed":
            exit_ = cap_status
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
            latency_ms=round((clock() - started) * 1000),
        )
        tracer.end_run(
            status=exit_, reply=response.text, stop=response.stop, model_calls=model_calls,
            tool_calls=tool_calls, usage=usage, cost_usd=cost, latency_ms=result.latency_ms,
        )
    return result
