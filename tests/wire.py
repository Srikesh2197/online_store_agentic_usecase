"""The scripted model behind a fake HTTP transport, plugged into the real LangChain chat models.

The hand loop's tests hand a `ScriptedModel` to our adapters as their `send`. Here the same
object answers HTTP requests made by the real `ChatOpenAI` and `ChatAnthropic`, so LangChain
builds a real request body and parses a real response body. `model.requests` then holds the
bodies LangChain sent, which is what the parity and guardrail tests compare. No network.

    setup = wire_setup(ScriptedModel("openai", calls(...), reply(...)), "openai")

The OpenAI SDK uses `httpx`; the Anthropic SDK (1.13) uses its fork `httpx2`. ChatOpenAI takes
an `http_client`; ChatAnthropic does not, so its cached `_client` is set directly.
"""

import json

import anthropic
import httpx
import httpx2
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from arl.framework.models import ChatSetup, chat_model_kwargs

MODELS = {"openai": "gpt-6-luna", "anthropic": "claude-haiku-5-5"}


def _handler(send, provider: str, lib):
    def handle(request):
        body = json.loads(request.content)
        response, request_id = send(body)
        n = len(getattr(send, "requests", [])) or 1
        # The scripted bodies leave out fields the SDKs expect on every response.
        if provider == "openai":
            response = {"id": f"resp_{n}", "object": "response", "created_at": 0,
                        "model": body["model"], **response}
        else:
            response = {"id": f"msg_{n}", "model": body["model"], **response}
        return lib.Response(200, json=response,
                            headers={"x-request-id": request_id, "request-id": request_id})
    return handle


def wire_setup(send, provider: str, model: str | None = None) -> ChatSetup:
    """A ChatSetup configured exactly as make_chat_model would, answering from `send`."""
    model = model or MODELS[provider]
    kwargs = chat_model_kwargs(model)
    del kwargs["model_provider"]
    if provider == "openai":
        client = httpx.Client(transport=httpx.MockTransport(_handler(send, provider, httpx)))
        chat = ChatOpenAI(model=model, api_key="test", http_client=client, **kwargs)
    else:
        chat = ChatAnthropic(model=model, api_key="test", **kwargs)
        client = httpx2.Client(transport=httpx2.MockTransport(_handler(send, provider, httpx2)),
                               base_url="http://anthropic.test")
        chat.__dict__["_client"] = anthropic.Anthropic(
            api_key="test", base_url="http://anthropic.test", max_retries=0, http_client=client)
    return ChatSetup(chat, provider, model)
