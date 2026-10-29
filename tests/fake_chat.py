"""A fake LangChain chat model that supports tool binding. No API calls, no HTTP.

LangChain's own fakes (GenericFakeChatModel, FakeMessagesListChatModel) raise
NotImplementedError on `bind_tools`, so an agent cannot be built on them. This one takes the
same neutral steps as tests/scripted.py and answers each call with the `AIMessage` that
ChatOpenAI (Responses API, output_version "responses/v1") would produce for that step:
content blocks in output order, parsed tool calls, `response_metadata` with the status, and
`usage_metadata`. Read it with `ChatSetup(fake, "openai", "gpt-6-luna")`.

Every call is recorded in `fake.calls`: the messages and the bound kwargs (tools,
tool_choice) plus `max_tokens`, so tests can see what the agent asked for.
"""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from scripted import USAGE, Step, _openai


def message_from_openai_body(body: dict) -> AIMessage:
    content, tool_calls, invalid = [], [], []
    for item in body["output"]:
        if item["type"] == "message":
            for part in item["content"]:
                if part["type"] == "output_text":
                    content.append({"type": "text", "text": part["text"], "id": item["id"]})
                else:
                    content.append({**part, "id": item["id"]})
            continue
        content.append(item)
        if item["type"] == "function_call":
            try:
                tool_calls.append({"name": item["name"], "args": json.loads(item["arguments"]),
                                   "id": item["call_id"], "type": "tool_call"})
            except json.JSONDecodeError as exc:
                invalid.append({"name": item["name"], "args": item["arguments"],
                                "id": item["call_id"], "error": str(exc),
                                "type": "invalid_tool_call"})
    metadata = {"status": body["status"], "model_provider": "openai"}
    if body.get("incomplete_details"):
        metadata["incomplete_details"] = body["incomplete_details"]
    usage = {"input_tokens": USAGE["input_tokens"], "output_tokens": USAGE["output_tokens"],
             "total_tokens": USAGE["input_tokens"] + USAGE["output_tokens"],
             "input_token_details": {"cache_read": 0}, "output_token_details": {"reasoning": 0}}
    return AIMessage(content=content, tool_calls=tool_calls, invalid_tool_calls=invalid,
                     response_metadata=metadata, usage_metadata=usage)


class FakeToolChatModel(BaseChatModel):
    steps: list[Step]
    calls: list[dict] = Field(default_factory=list)
    max_tokens: int = 2000

    @property
    def _llm_type(self) -> str:
        return "fake-tool-chat"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        n = len(self.calls)
        self.calls.append({"messages": list(messages), "max_tokens": self.max_tokens, **kwargs})
        if n >= len(self.steps):
            raise AssertionError(f"The script has {len(self.steps)} steps; call {n + 1} came.")
        message = message_from_openai_body(_openai(self.steps[n], n + 1))
        return ChatResult(generations=[ChatGeneration(message=message)])
