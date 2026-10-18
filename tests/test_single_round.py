"""The single round, driven by canned response bodies. No API calls."""

import json

from arl.foundations.single_round import run_single_round
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
        "Where is ORD-1001?", ticket_id="t", conn=conn, send=model, model="gpt-6-luna",
        tracer=tracer,
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
    outputs = second["input"][3:]
    assert [o["call_id"] for o in outputs] == ["call_a", "call_b"]
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
