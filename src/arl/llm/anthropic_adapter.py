"""The Anthropic Messages API behind the neutral interface.

The conversation is a list of messages whose roles alternate, each holding content
blocks. The model's call is a `tool_use` block whose `input` is an object; our result is
a `tool_result` block inside the next *user* message, placed before any text. Thinking
blocks must go back complete and unmodified within a tool-use turn.

Usage differs from OpenAI: `input_tokens` counts only uncached input, so the cache
reads and writes are added back to get the total.
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

PROVIDER = "anthropic"

_STOPS: dict[str, Stop] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_calls",
    "max_tokens": "max_tokens",
    "model_context_window_exceeded": "max_tokens",
    "refusal": "refusal",
    "pause_turn": "other",
}


def tool_to_wire(spec: ToolSpec) -> dict:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters,
        "strict": True,
    }


def anthropic_sender(client):
    """Send a request with the Anthropic SDK and return the response body as received."""

    def send(request: dict) -> tuple[dict, str | None]:
        raw = client.messages.with_raw_response.create(**request)
        # In the anthropic SDK `text` is a method; in the openai SDK it is a property.
        return json.loads(raw.text()), raw.headers.get("request-id")

    return send


def usage_from_anthropic(body: dict) -> Usage:
    usage = body.get("usage") or {}
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    return Usage(
        input_tokens=usage.get("input_tokens", 0) + cache_read + cache_write,
        cached_input_tokens=cache_read,
        output_tokens=usage.get("output_tokens", 0),
        reasoning_tokens=(usage.get("output_tokens_details") or {}).get("thinking_tokens", 0),
        cache_write_tokens=cache_write,
    )


def _content(message: Message) -> str | list[dict]:
    if message.role == "assistant" and message.provider == PROVIDER:
        # Our own model's blocks go back verbatim, thinking blocks and signatures included.
        return [part.native for part in message.parts]
    parts = message.parts
    if len(parts) == 1 and isinstance(parts[0], Text):
        return parts[0].text
    # tool_result blocks must come first in a user message.
    ordered = [p for p in parts if isinstance(p, ToolResult)] + [
        p for p in parts if not isinstance(p, ToolResult)
    ]
    blocks = []
    for part in ordered:
        match part:
            case ToolResult():
                block = {"type": "tool_result", "tool_use_id": part.call_id,
                         "content": part.content}
                if part.is_error:
                    block["is_error"] = True
                blocks.append(block)
            case Text():
                blocks.append({"type": "text", "text": part.text})
            case ToolCall():
                blocks.append({"type": "tool_use", "id": part.id, "name": part.name,
                               "input": json.loads(part.arguments)})
            case Reasoning():
                pass  # another provider's reasoning cannot be sent to Anthropic
    return blocks


class AnthropicAdapter:
    provider = PROVIDER

    def __init__(self, model: str, send, options: dict | None = None):
        self.model = model
        self.send = send
        self.options = options or {}

    def build_request(self, *, system: str, messages: list[Message], tools: list[ToolSpec],
                      tool_choice: ToolChoice, max_tokens: int) -> dict:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": _content(m)} for m in messages],
            "tools": [tool_to_wire(spec) for spec in tools],
            # Parallel calls are allowed by default; there is no separate flag to set.
            "tool_choice": {"type": tool_choice},
            **self.options,
        }

    def parse_response(self, body: dict) -> ModelResponse:
        parts = []
        for block in body.get("content", []):
            match block["type"]:
                case "thinking" | "redacted_thinking":
                    parts.append(Reasoning(block))
                case "text":
                    parts.append(Text(block["text"], native=block))
                case "tool_use":
                    parts.append(ToolCall(block["id"], block["name"], json.dumps(block["input"]),
                                          native=block))
                case other:
                    raise ValueError(f"Unexpected Anthropic content block type '{other}'.")
        provider_stop = body.get("stop_reason") or "unknown"
        return ModelResponse(PROVIDER, parts, _STOPS.get(provider_stop, "other"), provider_stop,
                             usage_from_anthropic(body), body)
