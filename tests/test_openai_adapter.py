"""The OpenAI adapter on hand-written bodies shaped like the Responses API docs."""

import pytest

from arl.llm.openai_adapter import OpenAIAdapter, tool_to_wire
from arl.llm.types import Message, Reasoning, Text, ToolCall, ToolResult, ToolSpec

SPEC = ToolSpec("get_order", "Get one order.", {
    "type": "object", "properties": {"order_id": {"type": "string", "description": "ID"}},
    "required": ["order_id"], "additionalProperties": False,
})
REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAA"}
CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "get_order",
        "arguments": '{"order_id":"ORD-1001"}', "status": "completed"}


def _message(*content):
    return {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": list(content)}


def _body(output, status="completed", **extra):
    return {"status": status, "output": output, **extra,
            "usage": {"input_tokens": 1000,
                      "input_tokens_details": {"cached_tokens": 600, "cache_write_tokens": 300},
                      "output_tokens": 80, "output_tokens_details": {"reasoning_tokens": 30}}}


ADAPTER = OpenAIAdapter("gpt-6-luna", send=None)


def test_tool_definition_is_a_strict_function():
    assert tool_to_wire(SPEC) == {"type": "function", "name": "get_order",
                                  "description": "Get one order.",
                                  "parameters": SPEC.parameters, "strict": True}


def test_parse_reasoning_and_two_parallel_calls():
    second = {**CALL, "id": "fc_2", "call_id": "call_2"}
    response = ADAPTER.parse_response(_body([REASONING, CALL, second]))
    assert response.parts == [
        Reasoning(REASONING),
        ToolCall("call_1", "get_order", '{"order_id":"ORD-1001"}', native=CALL),
        ToolCall("call_2", "get_order", '{"order_id":"ORD-1001"}', native=second),
    ]
    assert (response.stop, response.provider_stop) == ("tool_calls", "completed")


def test_parse_text_reply():
    item = _message({"type": "output_text", "text": "It ", "annotations": []},
                    {"type": "output_text", "text": "shipped.", "annotations": []})
    response = ADAPTER.parse_response(_body([item]))
    assert response.parts == [Text("It shipped.", native=item)]
    assert response.stop == "end"


def test_usage_includes_cached_tokens_in_input():
    usage = ADAPTER.parse_response(_body([])).usage
    assert (usage.input_tokens, usage.cached_input_tokens, usage.cache_write_tokens) == (
        1000, 600, 300)
    assert (usage.output_tokens, usage.reasoning_tokens) == (80, 30)


@pytest.mark.parametrize("body, stop, provider_stop", [
    (_body([], "incomplete", incomplete_details={"reason": "max_output_tokens"}),
     "max_tokens", "incomplete:max_output_tokens"),
    (_body([], "incomplete", incomplete_details={"reason": "content_filter"}),
     "refusal", "incomplete:content_filter"),
    (_body([_message({"type": "refusal", "refusal": "I can't help with that."})]),
     "refusal", "completed"),
    (_body([], "failed"), "other", "failed"),
])
def test_stop_is_derived_from_status(body, stop, provider_stop):
    response = ADAPTER.parse_response(body)
    assert (response.stop, response.provider_stop) == (stop, provider_stop)


def test_second_request_replays_items_then_outputs():
    response = ADAPTER.parse_response(_body([REASONING, CALL]))
    messages = [Message("user", [Text("Where is ORD-1001?")]), response.message(),
                Message("user", [ToolResult("call_1", '{"error": "x"}', is_error=True)])]
    request = ADAPTER.build_request(system="Be brief.", messages=messages, tools=[SPEC],
                                    tool_choice="none", max_tokens=2000)
    assert request["input"] == [
        {"role": "user", "content": "Where is ORD-1001?"},
        REASONING,
        CALL,
        # OpenAI has no error flag: the error is only in the output text.
        {"type": "function_call_output", "call_id": "call_1", "output": '{"error": "x"}'},
    ]
    assert request["tool_choice"] == "none" and request["store"] is False


def test_another_providers_turn_is_rebuilt_without_its_reasoning():
    turn = Message("assistant", [
        Reasoning({"type": "thinking", "thinking": "", "signature": "sig"}),
        Text("Checking."),
        ToolCall("toolu_1", "get_order", '{"order_id": "ORD-1001"}'),
    ], provider="anthropic")
    request = ADAPTER.build_request(system="", messages=[turn], tools=[], tool_choice="auto",
                                    max_tokens=10)
    assert request["input"] == [
        {"role": "assistant", "content": "Checking."},
        {"type": "function_call", "call_id": "toolu_1", "name": "get_order",
         "arguments": '{"order_id": "ORD-1001"}'},
    ]


def test_options_are_merged_into_the_request():
    adapter = OpenAIAdapter("gpt-6-luna", send=None, options={"reasoning": {"effort": "low"}})
    request = adapter.build_request(system="", messages=[], tools=[], tool_choice="auto",
                                    max_tokens=10)
    assert request["reasoning"] == {"effort": "low"}


def test_unknown_item_type_fails_loudly():
    with pytest.raises(ValueError, match="web_search_call"):
        ADAPTER.parse_response(_body([{"type": "web_search_call", "id": "ws_1"}]))
