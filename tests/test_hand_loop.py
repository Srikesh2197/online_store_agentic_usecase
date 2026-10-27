"""The hand-written loop (rung 2), driven by the scripted model on both providers.

No API calls. Each test scripts what the model says on each call and checks what the loop
did: which tools ran, what went back to the model, and how and why the run ended.
"""

import json

import pytest

from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.tasks import by_id, load_tasks
from arl.evals.transcript import Transcript
from arl.foundations.hand_loop import MAX_STEPS, run_hand_loop
from arl.foundations.single_round import CLOSING_INSTRUCTION
from arl.llm.anthropic_adapter import AnthropicAdapter
from arl.llm.openai_adapter import OpenAIAdapter
from arl.tracing.tracer import Tracer, read_events
from scripted import ScriptedModel, calls, is_tool_choice_none, other, refusal, reply, truncated

PROVIDERS = ["openai", "anthropic"]
ADAPTERS = {"openai": (OpenAIAdapter, "gpt-6-luna"),
            "anthropic": (AnthropicAdapter, "claude-haiku-5-5")}

LOOK = ("get_order", {"order_id": "ORD-1003"})
CANCEL = ("cancel_order", {"order_id": "ORD-1003", "reason": "Ordered the wrong desk lamp"})
CANCEL_TICKET = "Please cancel my order ORD-1003. I ordered the wrong desk lamp."


def _run(provider, conn, tmp_path, *steps, ticket=CANCEL_TICKET, ticket_id="t", **kwargs):
    cls, model_id = ADAPTERS[provider]
    model = ScriptedModel(provider, *steps)
    tracer = Tracer("test-run", log_dir=tmp_path)
    result = run_hand_loop(ticket, ticket_id=ticket_id, conn=conn,
                           adapter=cls(model_id, send=model), tracer=tracer, **kwargs)
    return result, model, read_events(tracer.path)


def _conversation(request: dict) -> list:
    return request.get("input", request.get("messages"))


def _results(provider: str, request: dict) -> list[dict]:
    """The tool results in the last user turn of a request."""
    if provider == "openai":
        return [i for i in request["input"] if i.get("type") == "function_call_output"]
    return [b for b in request["messages"][-1]["content"] if b["type"] == "tool_result"]


def _status(conn, order_id="ORD-1003") -> str:
    return conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()[0]


# --- Ending normally -------------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_reply_on_the_first_call_ends_the_loop(provider, conn, tmp_path):
    result, _model, events = _run(provider, conn, tmp_path, reply("Opened items can be returned."))
    assert (result.status, result.stop, result.model_calls, result.tool_calls) == (
        "completed", "end", 1, 0)
    assert result.reply == "Opened items can be returned."
    assert [e["type"] for e in events] == [
        "run_start", "model_request", "model_response", "loop_exit", "run_end"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_look_then_act_then_reply(provider, conn, tmp_path):
    result, model, events = _run(provider, conn, tmp_path,
                                 calls(LOOK), calls(CANCEL), reply("ORD-1003 is cancelled."))
    assert (result.status, result.model_calls, result.tool_calls) == ("completed", 3, 2)
    assert _status(conn) == "cancelled"
    # Every request carries the whole conversation so far, earlier turns unchanged.
    first, second, third = (_conversation(r) for r in model.requests)
    assert second[:len(first)] == first and third[:len(second)] == second
    assert len(first) < len(second) < len(third)
    assert all(not is_tool_choice_none(r) for r in model.requests)   # no closing instruction
    if provider == "anthropic":
        assert [m["role"] for m in third] == ["user", "assistant", "user", "assistant", "user"]
    assert [e["type"] for e in events] == [
        "run_start",
        "model_request", "model_response", "tool_call",
        "model_request", "model_response", "tool_call",
        "model_request", "model_response",
        "loop_exit", "run_end",
    ]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    responses = [e for e in events if e["type"] == "model_response"]
    assert events[-1]["cost_usd"] == pytest.approx(sum(e["cost_usd"] for e in responses))
    assert events[-2] == {**events[-2], "exit": "completed", "steps": 3}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_parallel_calls_get_one_result_each_in_order(provider, conn, tmp_path):
    both = calls(("get_order", {"order_id": "ORD-1001"}), ("get_shipment", {"order_id": "ORD-1001"}))
    result, model, _ = _run(provider, conn, tmp_path, both, reply("It is in transit."))
    assert (result.model_calls, result.tool_calls) == (2, 2)
    results = _results(provider, model.requests[1])
    ids = [r.get("call_id", r.get("tool_use_id")) for r in results]
    assert ids == (["call_1_0", "call_1_1"] if provider == "openai" else ["toolu_1_0", "toolu_1_1"])
    if provider == "anthropic":   # all results in one user message
        assert len(model.requests[1]["messages"]) == 3


# --- Tool errors are fed back -----------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_tool_error_goes_back_to_the_model(provider, conn, tmp_path):
    result, model, events = _run(provider, conn, tmp_path,
                                 calls(("get_order", {"order_id": "ORD-9999"})),
                                 reply("I could not find ORD-9999."))
    assert result.status == "completed"
    [sent] = _results(provider, model.requests[1])
    content = sent.get("output", sent.get("content"))
    assert json.loads(content)["error"] == "order_not_found"
    if provider == "anthropic":
        assert sent["is_error"] is True
    assert [e["is_error"] for e in events if e["type"] == "tool_call"] == [True]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_bad_arguments_and_unknown_tools_are_errors_the_model_can_fix(provider, conn, tmp_path):
    steps = [calls(("get_order", {"order": "ORD-1003"}), ("refund_everything", {})),
             calls(LOOK), reply("It is processing.")]
    if provider == "openai":   # only OpenAI sends arguments as a string, so only it can garble JSON
        steps.insert(0, calls(("get_order", '{"order_id": "ORD-10')))
    result, _model, events = _run(provider, conn, tmp_path, *steps)
    assert result.status == "completed"
    errors = [e["result"]["error"] for e in events if e["type"] == "tool_call" and e["is_error"]]
    expected = ["invalid_arguments", "unknown_tool"]
    assert errors == (["invalid_arguments"] + expected if provider == "openai" else expected)
    last_call = [e for e in events if e["type"] == "tool_call"][-1]
    assert not last_call["is_error"]   # the corrected call worked


def test_a_tool_that_raises_becomes_an_error_result(conn, tmp_path, monkeypatch):
    def broken(conn, name, arguments):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("arl.foundations.hand_loop.execute_tool", broken)
    result, model, _events = _run("openai", conn, tmp_path, calls(LOOK), reply("Sorry."))
    assert result.status == "completed"
    [sent] = _results("openai", model.requests[1])
    assert json.loads(sent["output"])["error"] == "tool_failed"
    assert "database is locked" not in sent["output"]   # internals stay out of the prompt


# --- Ending abnormally -----------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_truncated_text_ends_the_run(provider, conn, tmp_path):
    result, _model, _ = _run(provider, conn, tmp_path, truncated(text="Your order is"))
    assert (result.status, result.stop, result.model_calls) == ("truncated", "max_tokens", 1)
    assert result.reply == "Your order is"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_call_in_a_truncated_response_is_never_run(provider, conn, tmp_path):
    result, _model, events = _run(provider, conn, tmp_path, calls(LOOK), truncated(call=CANCEL))
    assert (result.status, result.model_calls, result.tool_calls) == ("truncated", 2, 1)
    assert _status(conn) == "processing"
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["get_order"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_refusal_ends_the_run(provider, conn, tmp_path):
    result, model, events = _run(provider, conn, tmp_path, refusal())
    assert (result.status, result.stop, result.model_calls) == ("refused", "refusal", 1)
    assert len(model.requests) == 1
    exit_event = next(e for e in events if e["type"] == "loop_exit")
    assert exit_event["detail"]   # what the provider said is logged


@pytest.mark.parametrize("provider", PROVIDERS)
def test_any_other_stop_ends_the_run(provider, conn, tmp_path):
    result, _, _ = _run(provider, conn, tmp_path, calls(LOOK), other())
    assert (result.status, result.stop, result.model_calls) == ("stopped", "other", 2)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_an_empty_reply_is_flagged(provider, conn, tmp_path):
    result, _, _ = _run(provider, conn, tmp_path, calls(LOOK), reply(""))
    assert (result.status, result.stop) == ("no_reply", "end")


# --- The step cap ----------------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_step_cap_reserves_the_last_call_for_an_honest_reply(provider, conn, tmp_path):
    steps = [calls(LOOK)] * (MAX_STEPS - 1) + [reply("I could not finish; ORD-1003 is processing.")]
    result, model, events = _run(provider, conn, tmp_path, *steps)
    assert (result.status, result.stop) == ("step_cap", "end")
    assert result.model_calls == len(model.requests) == MAX_STEPS
    assert result.tool_calls == MAX_STEPS - 1   # the calls from call 9 did run
    *earlier, last = model.requests
    assert not any(is_tool_choice_none(r) for r in earlier) and is_tool_choice_none(last)
    conversation = _conversation(last)
    if provider == "openai":
        assert conversation[-1] == {"role": "user", "content": CLOSING_INSTRUCTION}
        assert conversation[-2]["type"] == "function_call_output"
    else:   # the instruction follows the results in the same user message
        *results, closing = conversation[-1]["content"]
        assert closing == {"type": "text", "text": CLOSING_INSTRUCTION}
        assert [b["type"] for b in results] == ["tool_result"]
    types = [e["type"] for e in events]
    assert types.index("step_cap") == len(types) - 5   # just before the reply-only call
    assert events[-2]["exit"] == "step_cap"


def test_tool_calls_despite_tools_off_are_not_run(conn, tmp_path):
    steps = [calls(LOOK)] * (MAX_STEPS - 1) + [calls(CANCEL)]
    result, _, _ = _run("anthropic", conn, tmp_path, *steps)
    assert (result.status, result.stop, result.tool_calls) == ("stopped", "tool_calls", MAX_STEPS - 1)
    assert _status(conn) == "processing"


def test_a_smaller_cap_is_honoured(conn, tmp_path):
    result, model, _ = _run("openai", conn, tmp_path, calls(LOOK), calls(LOOK), reply("Done."),
                            max_steps=3)
    assert (result.status, len(model.requests)) == ("step_cap", 3)
    with pytest.raises(ValueError):
        _run("openai", conn, tmp_path, reply("x"), max_steps=1)


# --- Reasoning and grading -------------------------------------------------------------

@pytest.mark.parametrize("provider", PROVIDERS)
def test_reasoning_is_replayed_verbatim_on_every_later_call(provider, conn, tmp_path):
    _result, model, _ = _run(provider, conn, tmp_path, calls(LOOK, reasoning=True),
                            calls(CANCEL, reasoning=True), reply("Cancelled."))
    second, third = (json.dumps(_conversation(r)) for r in model.requests[1:])
    marker = "enc_1" if provider == "openai" else "sig_1"
    assert marker in second and marker in third
    assert ("enc_2" if provider == "openai" else "sig_2") in third


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_scripted_loop_run_passes_the_real_graders(provider, conn, tmp_path):
    task = by_id(load_tasks())["c07-cancel-processing"]
    before = snapshot(conn)
    cls, model_id = ADAPTERS[provider]
    tracer = Tracer("graded", log_dir=tmp_path)
    run_hand_loop(task.ticket.strip(), ticket_id=task.id, conn=conn, tracer=tracer,
                  adapter=cls(model_id, send=ScriptedModel(provider, calls(LOOK), calls(CANCEL),
                                                           reply("Your order ORD-1003 is cancelled."))))
    tracer.event("end_state", db_diff=diff(before, snapshot(conn)))
    transcript = Transcript.from_events(read_events(tracer.path))
    verdict = grade(task, transcript)
    assert verdict.success, [c for c in verdict.checks if not c.passed]
    assert transcript.strategy == "hand_loop" and transcript.status == "completed"
    assert [c.turn for c in transcript.tool_calls] == [1, 2]   # order rule: look, then act
