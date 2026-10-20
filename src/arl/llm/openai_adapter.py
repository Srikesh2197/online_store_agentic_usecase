"""The OpenAI Responses API behind the neutral interface.

The conversation is one flat list of typed items. The model's call is a
`function_call` item whose `arguments` is a JSON string; our result is a separate
`function_call_output` item. There is no stop-reason field: why the model stopped is
read from `status`, `incomplete_details` and whether any calls came back.
"""

import json

from arl.llm.types import (
    Message,
    ModelResponse,
    Reasoning,
    Stop,
    Text,
    ToolCall,
    ToolChoice,
    ToolResult,
    ToolSpec,
    Usage,
)

PROVIDER = "openai"


def tool_to_wire(spec: ToolSpec) -> dict:
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
        "strict": True,
    }


def openai_sender(client):
    """Send a request with the OpenAI SDK and return the response body as received."""

    def send(request: dict) -> tuple[dict, str | None]:
        raw = client.responses.with_raw_response.create(**request)
        return json.loads(raw.text), raw.headers.get("x-request-id")

    return send


def usage_from_openai(body: dict) -> Usage:
    usage = body.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    return Usage(
        input_tokens=usage.get("input_tokens", 0),
        cached_input_tokens=details.get("cached_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
        # Reported since GPT-5.6, and billed at 1.25x input on those models.
        cache_write_tokens=details.get("cache_write_tokens", 0),
    )


def _input_items(messages: list[Message]) -> list[dict]:
    items = []
    for message in messages:
        if message.role == "assistant" and message.provider == PROVIDER:
            # Our own model's output goes back verbatim, reasoning items included.
            items += [part.native for part in message.parts]
            continue
        for part in message.parts:
            match part:
                case ToolResult():
                    items.append({"type": "function_call_output", "call_id": part.call_id,
                                  "output": part.content})
                case Text():
                    items.append({"role": message.role, "content": part.text})
                case ToolCall():
                    items.append({"type": "function_call", "call_id": part.id,
                                  "name": part.name, "arguments": part.arguments})
                case Reasoning():
                    pass  # another provider's reasoning cannot be sent to OpenAI
    return items


def _stop(body: dict, parts: list) -> tuple[Stop, str]:
    status = body.get("status") or "unknown"
    reason = (body.get("incomplete_details") or {}).get("reason")
    provider_stop = f"{status}:{reason}" if reason else status
    refused = any(
        content["type"] == "refusal"
        for item in body.get("output", []) if item["type"] == "message"
        for content in item["content"]
    )
    if status == "incomplete":
        return {"max_output_tokens": "max_tokens", "content_filter": "refusal"}.get(
            reason, "other"), provider_stop
    if refused:
        return "refusal", provider_stop
    if any(isinstance(part, ToolCall) for part in parts):
        return "tool_calls", provider_stop
    return ("end" if status == "completed" else "other"), provider_stop


class OpenAIAdapter:
    provider = PROVIDER

    def __init__(self, model: str, send, options: dict | None = None):
        self.model = model
        self.send = send
        self.options = options or {}

    def build_request(self, *, system: str, messages: list[Message], tools: list[ToolSpec],
                      tool_choice: ToolChoice, max_tokens: int) -> dict:
        return {
            "model": self.model,
            "instructions": system,
            "input": _input_items(messages),
            "tools": [tool_to_wire(spec) for spec in tools],
            "tool_choice": tool_choice,
            "parallel_tool_calls": True,
            "max_output_tokens": max_tokens,
            # Stateless: OpenAI keeps nothing, so every request carries the whole conversation.
            "store": False,
            # Reasoning items come back encrypted so they can be returned in the next request.
            "include": ["reasoning.encrypted_content"],
            **self.options,
        }

    def parse_response(self, body: dict) -> ModelResponse:
        parts = []
        for item in body.get("output", []):
            match item["type"]:
                case "reasoning":
                    parts.append(Reasoning(item))
                case "message":
                    text = "".join(c["text"] for c in item["content"] if c["type"] == "output_text")
                    parts.append(Text(text, native=item))
                case "function_call":
                    parts.append(ToolCall(item["call_id"], item["name"], item["arguments"],
                                          native=item))
                case other:
                    raise ValueError(f"Unexpected OpenAI output item type '{other}'.")
        stop, provider_stop = _stop(body, parts)
        return ModelResponse(PROVIDER, parts, stop, provider_stop, usage_from_openai(body), body)
