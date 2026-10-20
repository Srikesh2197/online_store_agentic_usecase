"""Both adapters against real request and response bodies, recorded from live runs of t1.

The fixtures come from runs/*.jsonl of the Phase 1 smoke runs (2026-10-18). Replaying the
recorded responses through the single round must reproduce the recorded requests, so a
change to an adapter that alters what goes over the wire fails here.

`instructions`/`system` and `tools` are left out of the comparison: they follow the policy
and the tool descriptions, which are expected to change. Everything else must match.
"""

import json
from pathlib import Path

import pytest

from arl.foundations.single_round import run_single_round
from arl.llm.anthropic_adapter import AnthropicAdapter
from arl.llm.openai_adapter import OpenAIAdapter
from arl.tracing.tracer import Tracer

FIXTURES = Path(__file__).parent / "fixtures" / "recorded"
ADAPTERS = {"openai": OpenAIAdapter, "anthropic": AnthropicAdapter}
VARIABLE = {"instructions", "system", "tools"}


def _load(provider: str) -> dict:
    return json.loads((FIXTURES / f"{provider}_t1.json").read_text())


def _adapter(fixture: dict, send=None):
    from arl.llm.pricing import model_entry

    options = model_entry(fixture["model"]).get("request_options")
    return ADAPTERS[fixture["provider"]](fixture["model"], send=send, options=options)


def _fixed_part(request: dict) -> dict:
    return {k: v for k, v in request.items() if k not in VARIABLE}


@pytest.mark.parametrize("provider", ADAPTERS)
def test_recorded_first_response_parses(provider):
    fixture = _load(provider)
    response = _adapter(fixture).parse_response(fixture["responses"][0])
    assert response.stop == "tool_calls"
    [call] = response.tool_calls
    recorded = fixture["tool_calls"][0]
    assert (call.id, call.name) == (recorded["call_id"], recorded["name"])
    assert json.loads(call.arguments) == {"order_id": "ORD-1001"}


@pytest.mark.parametrize("provider", ADAPTERS)
def test_recorded_final_response_parses(provider):
    fixture = _load(provider)
    response = _adapter(fixture).parse_response(fixture["responses"][1])
    assert response.stop == "end"
    assert "ORD-1001" in response.text and "shipped" in response.text
    assert response.usage.input_tokens > 0 and response.usage.output_tokens > 0


@pytest.mark.parametrize("provider", ADAPTERS)
def test_replay_reproduces_the_recorded_requests(provider, conn, tmp_path):
    fixture = _load(provider)
    responses = list(fixture["responses"])
    sent = []

    def send(request):
        sent.append(request)
        return responses.pop(0), "req_replay"

    run_single_round(fixture["ticket"], ticket_id="t1", conn=conn,
                     adapter=_adapter(fixture, send), tracer=Tracer("replay", log_dir=tmp_path))

    assert len(sent) == len(fixture["requests"]) == 2
    for ours, recorded in zip(sent, fixture["requests"]):
        assert _fixed_part(ours) == _fixed_part(recorded)
        assert set(ours) == set(recorded)
