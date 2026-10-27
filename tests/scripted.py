"""A scripted fake model for either provider. No API calls.

A script is a list of neutral steps: what the model "says" on each call. The fake turns
each step into a real response body for its provider (OpenAI Responses items, or Anthropic
content blocks with a stop_reason), so the real adapters parse it. Tests therefore exercise
the actual stop-reason mapping and native replay, not a mock of them.

    calls(("get_order", {"order_id": "ORD-1003"}))   ask for one or more tools
    reply("Done.")                                   end with text
    truncated(text=..., call=...)                    cut off by the output limit
    refusal()                                        the model refuses
    other()                                          any other ending (failed, pause_turn)

Every request is recorded in `model.requests`, exactly as the adapter built it.
"""

import json
from dataclasses import dataclass, field

USAGE = {"input_tokens": 1000, "output_tokens": 100}


@dataclass(frozen=True)
class Step:
    kind: str                                   # tool_calls, end, max_tokens, refusal, other
    calls: list[tuple[str, dict | str]] = field(default_factory=list)
    text: str = ""
    reasoning: bool = False


def calls(*pairs: tuple[str, dict | str], text: str = "", reasoning: bool = False) -> Step:
    """Tool calls. Arguments are a dict, or a raw string (OpenAI only: may be invalid JSON)."""
    return Step("tool_calls", list(pairs), text, reasoning)


def reply(text: str, reasoning: bool = False) -> Step:
    return Step("end", text=text, reasoning=reasoning)


def truncated(text: str = "", call: tuple[str, dict | str] | None = None) -> Step:
    return Step("max_tokens", [call] if call else [], text)


def refusal() -> Step:
    return Step("refusal")


def other() -> Step:
    return Step("other")


class ScriptedModel:
    """A `send` callable for an adapter. Replays `steps` in order, one per request."""

    def __init__(self, provider: str, *steps: Step):
        self.provider = provider
        self.steps = list(steps)
        self.requests: list[dict] = []

    def __call__(self, request: dict) -> tuple[dict, str]:
        n = len(self.requests)
        self.requests.append(request)
        if n >= len(self.steps):
            raise AssertionError(f"The script has {len(self.steps)} steps; request {n + 1} came.")
        render = _openai if self.provider == "openai" else _anthropic
        return render(self.steps[n], n + 1), f"req_{n + 1}"


# --- OpenAI Responses ------------------------------------------------------------------

def _openai(step: Step, n: int) -> dict:
    output = []
    if step.reasoning:
        output.append({"type": "reasoning", "id": f"rs_{n}", "summary": [],
                       "encrypted_content": f"enc_{n}"})
    if step.text:
        output.append({"type": "message", "id": f"msg_{n}", "role": "assistant",
                       "status": "completed",
                       "content": [{"type": "output_text", "text": step.text, "annotations": []}]})
    if step.kind == "refusal":
        output.append({"type": "message", "id": f"msg_{n}", "role": "assistant",
                       "status": "completed",
                       "content": [{"type": "refusal", "refusal": "I can't help with that."}]})
    for i, (name, args) in enumerate(step.calls):
        cut = step.kind == "max_tokens"
        arguments = args if isinstance(args, str) else json.dumps(args)
        output.append({"type": "function_call", "id": f"fc_{n}_{i}", "call_id": f"call_{n}_{i}",
                       "name": name, "arguments": arguments[:-3] if cut else arguments,
                       "status": "incomplete" if cut else "completed"})
    body = {"status": "completed", "output": output, "usage": {
        **USAGE, "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0}}}
    if step.kind == "max_tokens":
        body |= {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    elif step.kind == "other":
        body["status"] = "failed"
    return body


# --- Anthropic Messages ----------------------------------------------------------------

_STOP_REASON = {"tool_calls": "tool_use", "end": "end_turn", "max_tokens": "max_tokens",
                "refusal": "refusal", "other": "pause_turn"}


def _anthropic(step: Step, n: int) -> dict:
    content = []
    if step.reasoning:
        content.append({"type": "thinking", "thinking": f"Thinking {n}.", "signature": f"sig_{n}"})
    if step.text:
        content.append({"type": "text", "text": step.text})
    for i, (name, args) in enumerate(step.calls):
        content.append({"type": "tool_use", "id": f"toolu_{n}_{i}", "name": name,
                        "input": json.loads(args) if isinstance(args, str) else args})
    body = {"type": "message", "role": "assistant", "content": content,
            "stop_reason": _STOP_REASON[step.kind], "usage": USAGE}
    if step.kind == "refusal":
        body["stop_details"] = {"type": "refusal", "category": None, "explanation": None}
    return body


def is_tool_choice_none(request: dict) -> bool:
    return request["tool_choice"] in ("none", {"type": "none"})
