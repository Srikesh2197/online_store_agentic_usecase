"""The reply judge, driven by a fake Anthropic sender. No API calls."""

import json

import pytest

from arl.evals.graders import judge as jg
from arl.evals.labels import Item, Label
from arl.evals.transcript import ToolCallRecord, Transcript


def _body(verdict="pass", critique="Matches the shipment.", codes=(), stop="end_turn",
          text=None):
    payload = text if text is not None else json.dumps(
        {"critique": critique, "failure_codes": list(codes), "verdict": verdict})
    return {"content": [{"type": "text", "text": payload}], "stop_reason": stop,
            "usage": {"input_tokens": 300, "output_tokens": 60,
                      "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0}}


class FakeSend:
    def __init__(self, *bodies):
        self.bodies, self.requests = list(bodies), []

    def __call__(self, request):
        self.requests.append(request)
        body = self.bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return body, "req_1"


def _item(n=1, reply="ORD-2003 is due on 2026-10-08."):
    return Item(f"L{n:02d}", "c05-delivery-estimate", "When will ORD-2003 arrive?",
                [{"turn": 1, "name": "get_shipment", "arguments": '{"order_id":"ORD-2003"}',
                  "result": {"shipment": {"estimated_delivery": "2026-10-08"}}, "is_error": False}],
                reply, model="gpt-6-luna", strategy="hand_loop", stratum="pass_r2",
                code_success=True, code_facts=True)


def test_schema_puts_critique_before_verdict_and_avoids_reasoning_fields():
    assert jg.OUTPUT_SCHEMA["required"] == ["critique", "failure_codes", "verdict"]
    assert list(jg.OUTPUT_SCHEMA["properties"]) == ["critique", "failure_codes", "verdict"]
    names = " ".join(jg.OUTPUT_SCHEMA["properties"]).lower()
    assert "reasoning" not in names and "thinking" not in names


def test_system_blocks_cache_the_last_block_and_carry_examples():
    blocks = jg.system_blocks([(_item(), Label("L01", "fail", "Invents a date."))])
    assert [("cache_control" in b) for b in blocks] == [False, False, True]
    assert "Invents a date." in blocks[-1]["text"] and '"verdict": "fail"' in blocks[-1]["text"]
    assert "Opened items that are not defective" in blocks[1]["text"]       # the policy
    without = jg.system_blocks([])
    assert "cache_control" in without[-1] and len(without) == 2


def test_prompt_hash_changes_with_the_examples():
    a = jg.prompt_hash(jg.system_blocks([]))
    b = jg.prompt_hash(jg.system_blocks([(_item(), Label("L01", "pass"))]))
    assert a != b and a == jg.prompt_hash(jg.system_blocks([]))


def test_request_is_structured_thinking_off_and_trimmed():
    tr = Transcript("c05-delivery-estimate", "When will ORD-2003 arrive?", "gpt-6-luna",
                    "hand_loop",
                    tool_calls=[ToolCallRecord(1, "get_shipment", '{"order_id":"ORD-2003"}',
                                               {"shipment": {"note": "x" * 5000}}, False)],
                    reply="Due 2026-10-08.", db_diff={})
    item = jg.item_from_transcript(tr, "c05#k1")
    request = jg.build_request("claude-haiku-5-5", jg.system_blocks([]), item, 400)
    assert request["thinking"] == {"type": "disabled"}
    assert request["output_config"]["format"]["type"] == "json_schema"
    content = request["messages"][0]["content"]
    assert "When will ORD-2003 arrive?" in content and "Due 2026-10-08." in content
    assert "[cut, " in content                                   # long results are trimmed
    for hidden in ("gpt-6-luna", "hand_loop", "success", "facts"):
        assert hidden not in content


@pytest.mark.parametrize("body, expected", [
    (_body("pass"), ("pass", None)),
    (_body("Fail", codes=["r1"]), ("fail", None)),                       # casing drifts
    (_body(stop="refusal"), (None, "refused")),
    (_body(stop="max_tokens"), (None, "truncated")),
    (_body(text="not json"), (None, "invalid JSON")),
    (_body(verdict="maybe"), (None, "unknown verdict")),
])
def test_parse_response(body, expected):
    verdict, _, codes, error = jg.parse_response(body)
    assert verdict == expected[0]
    assert (error or "").startswith(expected[1] or "")
    if verdict == "fail":
        assert codes == ["R1"]


def test_judge_costs_and_logs(tmp_path):
    from arl.tracing.tracer import Tracer, read_events

    tracer = Tracer("j", log_dir=tmp_path)
    send = FakeSend(_body("fail", "Says yes to a repeat refund.", ["R1"]))
    v = jg.Judge(send, tracer=tracer).judge(_item())
    assert (v.verdict, v.failure_codes, v.error) == ("fail", ["R1"], None)
    # 4000 cached at 0.01 + 300 fresh at 0.10 + 60 out at 0.50, per million
    assert v.cost_usd == pytest.approx((4000 * 0.01 + 300 * 0.10 + 60 * 0.50) / 1e6)
    assert [e["type"] for e in read_events(tracer.path)] == ["judge_request", "judge_response"]


def test_api_failure_is_a_judge_error_not_a_verdict():
    v = jg.Judge(FakeSend(RuntimeError("overloaded"))).judge(_item())
    assert v.verdict is None and "overloaded" in v.error


def test_batch_halts_at_the_cap_and_on_repeated_errors():
    judge = jg.Judge(FakeSend(*[_body() for _ in range(5)]))
    est = jg.estimate(judge, [_item(n) for n in range(5)])
    assert est.per_call_worst > est.per_call_expected > 0
    one_call = (4000 * 0.01 + 300 * 0.10 + 60 * 0.50) / 1e6
    # Room for two calls: before the third, spent (2 calls) + worst would cross the cap.
    verdicts, status, spent = jg.judge_batch(judge, [_item(n) for n in range(5)],
                                             cap_usd=0.001 + 1.5 * one_call,
                                             worst_per_call=0.001)
    assert status == "halted_cap" and len(verdicts) == 2
    assert spent == pytest.approx(2 * one_call)
    failing = jg.Judge(FakeSend(*[RuntimeError("x") for _ in range(5)]))
    verdicts, status, _ = jg.judge_batch(failing, [_item(n) for n in range(5)], 1.0, 0.001)
    assert status == "halted_errors" and len(verdicts) == 3


def test_judge_uses_the_configured_model():
    assert jg.Judge(FakeSend()).model == jg.judge_config()["model"] == "claude-haiku-5-5"
