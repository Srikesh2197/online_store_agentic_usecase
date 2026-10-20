"""Provider-neutral shapes for a conversation with a model.

Our code builds and reads these. An adapter translates them to one provider's wire
format and back. Two things are deliberately not translated:

- `Reasoning` parts are opaque. OpenAI reasoning items and Anthropic thinking blocks
  must go back unchanged, and only to the provider that produced them.
- Every part parsed from a response keeps the provider's original item or block in
  `native`, so an assistant turn is replayed to its own provider exactly as received.
"""

from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0          # all input tokens, cached and cache-written ones included
    cached_input_tokens: int = 0   # the part of input_tokens read from the prompt cache
    output_tokens: int = 0         # all output tokens, reasoning ones included
    reasoning_tokens: int = 0      # the part of output_tokens spent on reasoning
    cache_write_tokens: int = 0    # the part of input_tokens written to the cache (Anthropic)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(*(a + b for a, b in zip(asdict(self).values(), asdict(other).values())))


@dataclass(frozen=True)
class Text:
    text: str
    native: dict | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str            # OpenAI `call_id`, Anthropic `tool_use.id`
    name: str
    arguments: str     # a JSON string, as OpenAI sends it; Anthropic's object is serialised
    native: dict | None = None


@dataclass(frozen=True)
class Reasoning:
    native: dict       # an OpenAI reasoning item, or an Anthropic thinking/redacted_thinking block


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


Part = Text | ToolCall | Reasoning | ToolResult


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    parts: list[Part]
    provider: str | None = None    # who produced an assistant message; None for our own


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict   # a strict JSON schema, valid for both providers


# Why the model stopped, in our terms. `provider_stop` on the response keeps the original.
Stop = Literal["end", "tool_calls", "max_tokens", "refusal", "other"]


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    parts: list[Part]
    stop: Stop
    provider_stop: str
    usage: Usage
    raw: dict = field(repr=False)

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts if isinstance(part, Text))

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [part for part in self.parts if isinstance(part, ToolCall)]

    def message(self) -> Message:
        """This response as the assistant turn of the next request."""
        return Message("assistant", self.parts, provider=self.provider)


ToolChoice = Literal["auto", "none"]


class Adapter(Protocol):
    provider: str
    model: str

    def build_request(self, *, system: str, messages: list[Message], tools: list[ToolSpec],
                      tool_choice: ToolChoice, max_tokens: int) -> dict:
        """The request body exactly as it will be sent."""

    def parse_response(self, body: dict) -> ModelResponse:
        """Read a response body as received."""

    def send(self, request: dict) -> tuple[dict, str | None]:
        """Send a request body; return the response body and the provider's request id."""
