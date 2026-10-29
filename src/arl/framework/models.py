"""LangChain chat models, configured from config/models.yaml, and read back in our terms.

The foundations build each request body themselves (llm/ adapters). Here LangChain builds
it: `init_chat_model` picks the provider class, and the chat model turns LangChain messages
into the wire format and the response back into an `AIMessage`. What this module adds:

    make_chat_model(model)   the chat model with the same settings our adapters send:
                             stateless OpenAI Responses with encrypted reasoning returned;
                             Anthropic with the thinking and cache settings from config
    bind(...)                tools and tool_choice, per provider. ChatAnthropic reads the
                             string "none" as "force a tool named none" (and then drops it,
                             because thinking is on), so "none" is sent as {"type": "none"}
    usage_of(msg)            our Usage, so llm/pricing.py prices the call as before
    stop_of(msg)             our neutral stop reason, the only thing the loops branch on
    tool_calls_of(msg)       the calls in output order, with the arguments as the model sent
                             them (a raw JSON string, possibly invalid)
    traced_call(...)         one model call, logged by our Tracer like the loops' calls
"""

import json
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, messages_to_dict
from langchain_core.runnables import Runnable

from arl.foundations.single_round import MAX_OUTPUT_TOKENS
from arl.llm.anthropic_adapter import _STOPS as ANTHROPIC_STOPS
from arl.llm.anthropic_adapter import tool_to_wire as anthropic_tool
from arl.llm.pricing import cost_usd, model_entry, price_for
from arl.llm.types import Stop, ToolCall, ToolChoice, ToolSpec, Usage

MAX_RETRIES = 2   # the SDK default in both providers, made explicit (Stage 5: API retries)


@dataclass(frozen=True)
class ChatSetup:
    """A chat model and what is needed to call it the way our adapters do."""
    chat: BaseChatModel
    provider: str                  # "openai" or "anthropic": how its messages are read
    model: str

    def with_max_tokens(self, max_tokens: int) -> "ChatSetup":
        return ChatSetup(self.chat.model_copy(update={"max_tokens": max_tokens}),
                         self.provider, self.model)


def chat_model_kwargs(model: str) -> dict:
    """`init_chat_model` keyword arguments, from the model's entry in config/models.yaml."""
    entry = model_entry(model)
    provider = entry["provider"]
    options = dict(entry.get("request_options") or {})
    kwargs = {"model_provider": provider, "max_tokens": MAX_OUTPUT_TOKENS,
              "max_retries": MAX_RETRIES}
    if provider == "openai":
        # As OpenAIAdapter: stateless (ChatOpenAI defaults to store=True on the Responses
        # API), and reasoning returned encrypted so it can be sent back on the next call.
        kwargs |= {"use_responses_api": True, "store": False,
                   "include": ["reasoning.encrypted_content"], **options}
    elif provider == "anthropic":
        if "thinking" in options:
            kwargs["thinking"] = options.pop("thinking")
        if options:   # e.g. top-level cache_control: merged into every request body
            kwargs["model_kwargs"] = options
    else:
        raise ValueError(f"Model '{model}' has unknown provider '{provider}'.")
    return kwargs


def make_chat_model(model: str) -> ChatSetup:
    from langchain.chat_models import init_chat_model

    kwargs = chat_model_kwargs(model)
    return ChatSetup(init_chat_model(model, **kwargs), kwargs["model_provider"], model)


def _openai_tool(spec: ToolSpec) -> dict:
    return {"type": "function", "function": {"name": spec.name, "description": spec.description,
                                             "parameters": spec.parameters, "strict": True}}


def bind(setup: ChatSetup, tools: list[ToolSpec], tool_choice: ToolChoice) -> Runnable:
    """The chat model with our tools bound, ready to invoke with a list of messages."""
    if setup.provider == "anthropic":
        return setup.chat.bind_tools([anthropic_tool(t) for t in tools],
                                     tool_choice={"type": tool_choice})
    return setup.chat.bind_tools([_openai_tool(t) for t in tools], tool_choice=tool_choice,
                                 parallel_tool_calls=True, strict=True)


# --- Reading a response --------------------------------------------------------------------

def usage_of(message: AIMessage) -> Usage:
    """LangChain's usage_metadata in our terms. Input tokens include cached and cache-written
    ones for both providers (LangChain adds them back for Anthropic, as our adapter does)."""
    usage = message.usage_metadata or {}
    inputs = usage.get("input_token_details") or {}
    outputs = usage.get("output_token_details") or {}
    cache_write = sum(inputs.get(key) or 0 for key in
                      ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"))
    reasoning = outputs.get("reasoning") or 0
    if not reasoning:
        # Anthropic thinking tokens are not mapped by LangChain; the raw usage still has them.
        raw = (message.response_metadata.get("usage") or {}).get("output_tokens_details") or {}
        reasoning = raw.get("thinking_tokens") or 0
    return Usage(input_tokens=usage.get("input_tokens", 0),
                 cached_input_tokens=inputs.get("cache_read") or 0,
                 output_tokens=usage.get("output_tokens", 0),
                 reasoning_tokens=reasoning,
                 cache_write_tokens=cache_write)


def _blocks(message: AIMessage) -> list[dict]:
    return [b for b in message.content if isinstance(b, dict)] if isinstance(
        message.content, list) else []


def tool_calls_of(message: AIMessage) -> list[ToolCall]:
    """The calls in the order the model made them, as neutral ToolCalls.

    LangChain splits calls into `tool_calls` (parsed) and `invalid_tool_calls` (bad JSON),
    which loses their order. The content blocks keep it, and keep OpenAI's arguments as the
    exact string the model sent, so execute_tool sees what it sees in the hand loop.
    """
    calls = []
    for block in _blocks(message):
        if block.get("type") == "function_call":
            calls.append(ToolCall(block["call_id"], block["name"], block["arguments"]))
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(block["id"], block["name"], json.dumps(block["input"])))
    if calls:
        return calls
    return ([ToolCall(c["id"], c["name"], json.dumps(c["args"])) for c in message.tool_calls]
            + [ToolCall(c["id"], c["name"], c.get("args") or "")
               for c in message.invalid_tool_calls])


def stop_of(message: AIMessage, provider: str) -> tuple[Stop, str]:
    """The neutral stop reason, mapped exactly as the llm/ adapters map the raw body."""
    meta = message.response_metadata
    if provider == "anthropic":
        provider_stop = meta.get("stop_reason") or "unknown"
        return ANTHROPIC_STOPS.get(provider_stop, "other"), provider_stop
    status = meta.get("status") or "unknown"
    reason = (meta.get("incomplete_details") or {}).get("reason")
    provider_stop = f"{status}:{reason}" if reason else status
    if status == "incomplete":
        return {"max_output_tokens": "max_tokens", "content_filter": "refusal"}.get(
            reason, "other"), provider_stop
    if any(block.get("type") == "refusal" for block in _blocks(message)):
        return "refusal", provider_stop
    if tool_calls_of(message):
        return "tool_calls", provider_stop
    return ("end" if status == "completed" else "other"), provider_stop


def refusal_detail(message: AIMessage, provider: str) -> str | None:
    """What the provider said about a refusal, for the log (as hand_loop.refusal_detail)."""
    stop, provider_stop = stop_of(message, provider)
    if stop != "refusal":
        return None
    if provider == "anthropic":
        return json.dumps(message.response_metadata.get("stop_details"))
    return " ".join(b.get("refusal", "") for b in _blocks(message)
                    if b.get("type") == "refusal") or provider_stop


# --- One traced call -----------------------------------------------------------------------

def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def traced_call(runnable: Runnable, messages: list[AnyMessage], *, setup: ChatSetup,
                system: str, tool_choice: str, max_tokens: int, index: int, tracer,
                echo=lambda title, payload: None):
    """Invoke `runnable` (a bound chat model, or a structured-output chain with
    include_raw=True) and log it as model call `index`, as the loops log theirs.

    The logged request is LangChain's view (messages as dicts), not the wire body, which
    LangChain builds out of our sight. Returns (output, the AIMessage, Usage, cost).
    """
    request = {"model": setup.model, "via": "langchain", "system": system,
               "messages": _jsonable(messages_to_dict(messages)),
               "tool_choice": tool_choice, "max_tokens": max_tokens}
    echo(f"REQUEST {index} ({setup.provider}, via LangChain)", request)
    with tracer.model_call(index, request, provider=setup.provider) as record:
        output = runnable.invoke([SystemMessage(system), *messages])
        response = output["raw"] if isinstance(output, dict) else output
        usage = usage_of(response)
        stop, provider_stop = stop_of(response, setup.provider)
        call_cost = cost_usd(usage, price_for(setup.model))
        body = _jsonable(response.model_dump())
        record.finish(response=body, usage=usage, cost_usd=call_cost,
                      request_id=response.response_metadata.get("id"), stop=stop,
                      provider_stop=provider_stop)
    echo(f"RESPONSE {index} (stop: {stop} / {provider_stop})", body)
    return output, response, usage, call_cost
