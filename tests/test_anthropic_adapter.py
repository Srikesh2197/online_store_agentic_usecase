"""The Anthropic adapter on hand-written bodies shaped like the Messages API docs."""

import json

import pytest

from arl.llm.anthropic_adapter import AnthropicAdapter, tool_to_wire, usage_from_anthropic
from arl.llm.openai_adapter import OpenAIAdapter
from arl.llm.types import Message, Reasoning, Text, ToolCall, ToolResult, ToolSpec

SPEC = ToolSpec("get_order", "Get one order.", {
    "type": "object", "properties": {"order_id": {"type": "string", "description": "ID"}},
    "required": ["order_id"], "additionalProperties": False,
})
THINKING = {"type": "thinking", "thinking": "Look up the order.", "signature": "EqQBsig"}
TOOL_USE = {"type": "tool_use", "id": "toolu_01A", "name": "get_order",
            "input": {"order_id": "ORD-1001"}}


def _body(content, stop_reason="tool_use", **usage):
    return {"id": "msg_01", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 50, **usage}}


def _adapter(options=None):
    return AnthropicAdapter("claude-haiku-5-5", send=None, options=options)


def _request(adapter, messages, tool_choice="auto"):
    return adapter.build_request(system="Be brief.", messages=messages, tools=[SPEC],
                                 tool_choice=tool_choice, max_tokens=2000)


def test_tool_definition_uses_input_schema_and_strict():
    assert tool_to_wire(SPEC) == {"name": "get_order", "description": "Get one order.",
                                  "input_schema": SPEC.parameters, "strict": True}


def test_first_request_shape():
    request = _request(_adapter({"thinking": {"type": "adaptive"}}),
                       [Message("user", [Text("Where is ORD-1001?")])])
    assert request == {
        "model": "claude-haiku-5-5",
        "max_tokens": 2000,
        "system": "Be brief.",
        "messages": [{"role": "user", "content": "Where is ORD-1001?"}],
        "tools": [tool_to_wire(SPEC)],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "adaptive"},
    }


def test_parse_thinking_text_and_tool_use():
    text = {"type": "text", "text": "Let me check."}
    response = _adapter().parse_response(_body([THINKING, text, TOOL_USE]))
    assert response.parts == [Reasoning(THINKING), Text("Let me check.", native=text),
                              ToolCall("toolu_01A", "get_order", '{"order_id": "ORD-1001"}',
                                       native=TOOL_USE)]
    assert (response.stop, response.provider_stop) == ("tool_calls", "tool_use")
    assert json.loads(response.tool_calls[0].arguments) == {"order_id": "ORD-1001"}
    assert response.text == "Let me check."


def test_second_request_replays_the_turn_verbatim_with_results_first():
    adapter = _adapter()
    response = adapter.parse_response(_body([THINKING, TOOL_USE]))
    messages = [
        Message("user", [Text("Where is ORD-1001?")]),
        response.message(),
        Message("user", [ToolResult("toolu_01A", '{"order": {}}'),
                         ToolResult("toolu_01B", '{"error": "x"}', is_error=True)]),
    ]
    request = _request(adapter, messages, tool_choice="none")
    assert request["tool_choice"] == {"type": "none"}
    assert request["tools"] == [tool_to_wire(SPEC)]
    assert request["messages"][1] == {"role": "assistant", "content": [THINKING, TOOL_USE]}
    assert request["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_01A", "content": '{"order": {}}'},
        {"type": "tool_result", "tool_use_id": "toolu_01B", "content": '{"error": "x"}',
         "is_error": True},
    ]}


def test_tool_results_go_before_text_in_a_user_message():
    message = Message("user", [Text("Thanks."), ToolResult("toolu_01A", "{}")])
    content = _request(_adapter(), [message])["messages"][0]["content"]
    assert [block["type"] for block in content] == ["tool_result", "text"]


def test_another_providers_turn_is_rebuilt_without_its_reasoning():
    openai_turn = OpenAIAdapter("gpt-6-luna", send=None).parse_response({
        "status": "completed",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAA"},
            {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "get_order",
             "arguments": '{"order_id":"ORD-1001"}', "status": "completed"},
        ],
    }).message()
    content = _request(_adapter(), [openai_turn])["messages"][0]["content"]
    assert content == [{"type": "tool_use", "id": "call_1", "name": "get_order",
                        "input": {"order_id": "ORD-1001"}}]


@pytest.mark.parametrize("stop_reason, stop", [
    ("end_turn", "end"), ("stop_sequence", "end"), ("tool_use", "tool_calls"),
    ("max_tokens", "max_tokens"), ("model_context_window_exceeded", "max_tokens"),
    ("refusal", "refusal"), ("pause_turn", "other"), ("something_new", "other"),
])
def test_stop_reasons(stop_reason, stop):
    response = _adapter().parse_response(_body([{"type": "text", "text": "x"}], stop_reason))
    assert (response.stop, response.provider_stop) == (stop, stop_reason)


def test_usage_adds_cache_reads_and_writes_back_into_input():
    usage = usage_from_anthropic(_body([], cache_read_input_tokens=800,
                                       cache_creation_input_tokens=300,
                                       output_tokens_details={"thinking_tokens": 20}))
    assert usage.input_tokens == 100 + 800 + 300
    assert (usage.cached_input_tokens, usage.cache_write_tokens) == (800, 300)
    assert (usage.output_tokens, usage.reasoning_tokens) == (50, 20)


def test_usage_without_cache_fields():
    usage = usage_from_anthropic(_body([]))
    assert (usage.input_tokens, usage.cached_input_tokens, usage.cache_write_tokens) == (100, 0, 0)


def test_unknown_block_type_fails_loudly():
    with pytest.raises(ValueError, match="server_tool_use"):
        _adapter().parse_response(_body([{"type": "server_tool_use", "id": "s", "name": "x"}]))


def test_sender_reads_the_raw_body_and_request_id():
    from types import SimpleNamespace

    from arl.llm.anthropic_adapter import anthropic_sender

    sent = {}

    def create(**request):
        sent.update(request)
        return SimpleNamespace(text=lambda: '{"content": []}', headers={"request-id": "req_1"})

    client = SimpleNamespace(messages=SimpleNamespace(
        with_raw_response=SimpleNamespace(create=create)))
    assert anthropic_sender(client)({"model": "m"}) == ({"content": []}, "req_1")
    assert sent == {"model": "m"}
