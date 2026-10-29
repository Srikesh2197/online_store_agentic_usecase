"""The LangChain model layer, read back in our terms. No API calls.

The same response body is parsed twice: by our adapter (llm/), and by the real LangChain chat
model behind a fake transport (tests/wire.py). Usage, cost, the neutral stop reason, the tool
calls and the text must come out the same, or the graph's cost accounting and branching would
drift from the loops'.
"""

import pytest
from langchain_core.messages import HumanMessage

from arl.framework.models import (
    chat_model_kwargs,
    make_chat_model,
    stop_of,
    tool_calls_of,
    usage_of,
)
from arl.llm.anthropic_adapter import AnthropicAdapter
from arl.llm.openai_adapter import OpenAIAdapter
from arl.llm.pricing import cost_usd, price_for
from scripted import ScriptedModel, calls, other, refusal, reply, truncated
from wire import MODELS, wire_setup

ADAPTERS = {"openai": OpenAIAdapter, "anthropic": AnthropicAdapter}

# Usage with every field set, per provider, as the APIs report it.
RICH_USAGE = {
    "openai": {"input_tokens": 3000, "output_tokens": 220,
               "input_tokens_details": {"cached_tokens": 2000, "cache_write_tokens": 500},
               "output_tokens_details": {"reasoning_tokens": 50}},
    "anthropic": {"input_tokens": 200, "output_tokens": 180, "cache_read_input_tokens": 2500,
                  "cache_creation_input_tokens": 300,
                  "output_tokens_details": {"thinking_tokens": 40}},
}

STEPS = {
    "tool calls": calls(("get_order", {"order_id": "ORD-1002"}),
                        ("get_shipment", {"order_id": "ORD-1002"}), reasoning=True),
    "reply": reply("It has shipped.", reasoning=True),
    "truncated": truncated(text="Your order"),
    "refusal": refusal(),
    "other": other(),
}


class RichUsage:
    """The scripted model, reporting RICH_USAGE instead of its plain usage."""

    def __init__(self, provider, step):
        self.inner, self.provider = ScriptedModel(provider, step), provider
        self.requests = self.inner.requests

    def __call__(self, request):
        body, request_id = self.inner(request)
        return {**body, "usage": RICH_USAGE[self.provider]}, request_id


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("name", STEPS)
def test_langchain_reads_a_response_as_our_adapter_does(provider, name):
    send = RichUsage(provider, STEPS[name])
    message = wire_setup(send, provider).chat.invoke([HumanMessage("hi")])
    body, _ = RichUsage(provider, STEPS[name])({"model": MODELS[provider]})
    body = {"id": "x", "model": MODELS[provider], **body}
    ours = ADAPTERS[provider](MODELS[provider], send=None).parse_response(body)

    assert usage_of(message) == ours.usage
    price = price_for(MODELS[provider])
    assert cost_usd(usage_of(message), price) == pytest.approx(cost_usd(ours.usage, price))
    assert stop_of(message, provider) == (ours.stop, ours.provider_stop)
    assert [(c.id, c.name, c.arguments) for c in tool_calls_of(message)] == [
        (c.id, c.name, c.arguments) for c in ours.tool_calls]
    assert message.text == ours.text


def test_the_options_follow_the_config():
    assert chat_model_kwargs("gpt-6-luna") == {
        "model_provider": "openai", "max_tokens": 2000, "max_retries": 2,
        "use_responses_api": True, "store": False, "include": ["reasoning.encrypted_content"]}
    assert chat_model_kwargs("claude-haiku-5-5") == {
        "model_provider": "anthropic", "max_tokens": 2000, "max_retries": 2,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "model_kwargs": {"cache_control": {"type": "ephemeral"}}}


def test_init_chat_model_builds_each_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    openai = make_chat_model("gpt-6-luna")
    assert type(openai.chat).__name__ == "ChatOpenAI" and openai.provider == "openai"
    assert openai.chat.store is False and openai.chat.use_responses_api is True
    haiku = make_chat_model("claude-haiku-5-5")
    assert type(haiku.chat).__name__ == "ChatAnthropic" and haiku.provider == "anthropic"
    assert haiku.with_max_tokens(4000).chat.max_tokens == 4000
    with pytest.raises(KeyError):
        make_chat_model("no-such-model")
