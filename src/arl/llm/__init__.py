"""Provider adapters behind one interface. The model id decides the provider."""

from arl.llm.pricing import model_entry


def make_adapter(model: str):
    """The adapter for `model`, using its `provider` and `request_options` from config."""
    entry = model_entry(model)
    options = entry.get("request_options") or {}
    match entry["provider"]:
        case "openai":
            from openai import OpenAI

            from arl.llm.openai_adapter import OpenAIAdapter, openai_sender

            return OpenAIAdapter(model, openai_sender(OpenAI()), options)
        case "anthropic":
            from anthropic import Anthropic

            from arl.llm.anthropic_adapter import AnthropicAdapter, anthropic_sender

            return AnthropicAdapter(model, anthropic_sender(Anthropic()), options)
        case other:
            raise ValueError(f"Model '{model}' has unknown provider '{other}'.")
