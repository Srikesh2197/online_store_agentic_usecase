"""The single round, driven by canned response bodies. No API calls."""

import json

from arl.foundations.single_round import CLOSING_INSTRUCTION, run_single_round
from arl.llm import make_adapter
from arl.llm.anthropic_adapter import AnthropicAdapter
from arl.llm.openai_adapter import OpenAIAdapter
from arl.tracing.tracer import Tracer, read_events

USAGE = {
    "input_tokens": 1000,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens": 100,
    "output_tokens_details": {"reasoning_tokens": 0},
}


def _function_call(call_id, name, **arguments):
    return {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id, "name": name,
            "arguments": json.dumps(arguments), "status": "completed"}


def _message(text):
    return {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


class CannedModel:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return {"status": "completed", "output": self.outputs.pop(0), "usage": USAGE}, "req_test"


def _run(conn, tmp_path, model):
    tracer = Tracer("test-run", log_dir=tmp_path)
    result = run_single_round(
        "Where is ORD-1001?", ticket_id="t", conn=conn,
        adapter=OpenAIAdapter("gpt-6-luna", send=model), tracer=tracer,
    )
    return result, read_events(tracer.path)


def test_two_tool_calls_then_reply(conn, tmp_path):
    calls = [
        _function_call("call_a", "get_order", order_id="ORD-1001"),
        _function_call("call_b", "get_shipment", order_id="ORD-9999"),
    ]
    model = CannedModel(calls, [_message("It is in transit.")])
    result, events = _run(conn, tmp_path, model)

    assert (result.status, result.reply) == ("completed", "It is in transit.")
    assert (result.model_calls, result.tool_calls) == (2, 2)
    assert result.usage.input_tokens == 2000
    assert result.cost_usd > 0

    first, second = model.requests
    assert first["tool_choice"] == "auto" and first["store"] is False
    assert second["tool_choice"] == "none"
    assert second["tools"] == first["tools"]
    # user message, the model's two calls verbatim, then one result per call
    assert second["input"][0] == first["input"][0]
    assert second["input"][1:3] == calls
    outputs = second["input"][3:5]
    assert [o["call_id"] for o in outputs] == ["call_a", "call_b"]
    # the closing instruction comes last, as a user message
    assert second["input"][5] == {"role": "user", "content": CLOSING_INSTRUCTION}
    assert json.loads(outputs[0]["output"])["order"]["id"] == "ORD-1001"
    assert json.loads(outputs[1]["output"])["error"] == "order_not_found"

    assert [e["type"] for e in events] == [
        "run_start", "model_request", "model_response", "tool_call", "tool_call",
        "model_request", "model_response", "run_end",
    ]
    assert [e["seq"] for e in events] == list(range(1, 9))
    assert events[4]["is_error"] is True
    assert events[-1]["cost_usd"] == result.cost_usd


def test_no_tool_call_means_one_model_call(conn, tmp_path):
    model = CannedModel([_message("Opened items can be returned if defective.")])
    result, events = _run(conn, tmp_path, model)

    assert (result.model_calls, result.tool_calls) == (1, 0)
    assert result.reply.startswith("Opened items")
    assert len(model.requests) == 1
    assert [e["type"] for e in events] == [
        "run_start", "model_request", "model_response", "run_end",
    ]


def test_run_without_reply_text_is_flagged(conn, tmp_path):
    model = CannedModel([_function_call("call_a", "get_order", order_id="ORD-1001")], [])
    result, _ = _run(conn, tmp_path, model)
    assert result.status == "no_reply"


# The same round through the Anthropic adapter.

ANTHROPIC_USAGE = {"input_tokens": 50, "cache_creation_input_tokens": 900,
                   "cache_read_input_tokens": 0, "output_tokens": 100}
THINKING = {"type": "thinking", "thinking": "Two lookups.", "signature": "EqQBsig"}


def _tool_use(call_id, name, **arguments):
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


class CannedClaude(CannedModel):
    def __call__(self, request):
        self.requests.append(request)
        content, stop_reason = self.outputs.pop(0)
        return {"type": "message", "role": "assistant", "content": content,
                "stop_reason": stop_reason, "usage": ANTHROPIC_USAGE}, "req_test"


def test_same_round_on_anthropic(conn, tmp_path):
    calls = [THINKING, _tool_use("toolu_a", "get_order", order_id="ORD-1001"),
             _tool_use("toolu_b", "get_shipment", order_id="ORD-9999")]
    model = CannedClaude((calls, "tool_use"),
                         ([{"type": "text", "text": "It is in transit."}], "end_turn"))
    tracer = Tracer("test-run", log_dir=tmp_path)
    result = run_single_round(
        "Where is ORD-1001?", ticket_id="t", conn=conn,
        adapter=AnthropicAdapter("claude-haiku-5-5", send=model), tracer=tracer,
    )
    events = read_events(tracer.path)

    assert (result.status, result.reply, result.stop) == ("completed", "It is in transit.", "end")
    assert (result.model_calls, result.tool_calls) == (2, 2)
    assert (result.usage.input_tokens, result.usage.cache_write_tokens) == (1900, 1800)

    first, second = model.requests
    assert first["tool_choice"] == {"type": "auto"}
    assert second["tool_choice"] == {"type": "none"}
    user, assistant, results = second["messages"]
    assert user == first["messages"][0]
    assert assistant == {"role": "assistant", "content": calls}   # thinking block included
    *tool_results, closing = results["content"]
    assert [r["tool_use_id"] for r in tool_results] == ["toolu_a", "toolu_b"]
    assert closing == {"type": "text", "text": CLOSING_INSTRUCTION}   # after the results
    assert "is_error" not in results["content"][0]
    assert results["content"][1]["is_error"] is True
    assert json.loads(results["content"][1]["content"])["error"] == "order_not_found"

    assert {e["provider"] for e in events if e["type"].startswith("model_")} == {"anthropic"}
    assert [e["stop"] for e in events if e["type"] == "model_response"] == ["tool_calls", "end"]
    # The tool sees the same JSON-string arguments whichever provider sent the call.
    assert events[3]["arguments"] == '{"order_id": "ORD-1001"}'


def test_make_adapter_follows_the_model_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert make_adapter("gpt-6-luna").provider == "openai"
    claude = make_adapter("claude-haiku-5-5")
    assert claude.provider == "anthropic"
    assert claude.options["thinking"] == {"type": "adaptive", "display": "summarized"}
