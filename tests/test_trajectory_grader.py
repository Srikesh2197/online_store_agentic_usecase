"""The trajectory grader on hand-made transcripts, and the combined verdict."""

from arl.evals.graders import grade
from arl.evals.graders.trajectory import check_must_call, check_must_not_call, check_order
from eval_helpers import call, inserted, make_task, make_transcript, refund_row


def _task(**trajectory):
    return make_task(trajectory=trajectory)


# --- must_call -----------------------------------------------------------------------

def test_must_call_passes_on_a_successful_call():
    [check] = check_must_call(_task(must_call=["get_order"]),
                              make_transcript(call(1, "get_order", order_id="ORD-1001")))
    assert check.passed and "turn 1" in check.detail


def test_must_call_fails_when_the_only_call_errored():
    [check] = check_must_call(_task(must_call=["get_order"]),
                              make_transcript(call(1, "get_order", is_error=True, order_id="X")))
    assert not check.passed and "none successful" in check.detail


def test_must_call_fails_when_never_called():
    [check] = check_must_call(_task(must_call=["get_shipment"]), make_transcript())
    assert not check.passed and check.detail == "never called"


def test_must_call_arguments_match_ignoring_case():
    task = _task(must_call=[{"tool": "get_order", "args": {"order_id": "ORD-1001"}}])
    [ok] = check_must_call(task, make_transcript(call(1, "get_order", order_id="ord-1001")))
    [wrong] = check_must_call(task, make_transcript(call(1, "get_order", order_id="ORD-1002")))
    assert ok.passed and not wrong.passed


# --- must_not_call -------------------------------------------------------------------

def test_must_not_call_passes_when_avoided():
    [check] = check_must_not_call(_task(must_not_call=["cancel_order"]),
                                  make_transcript(call(1, "get_order", order_id="ORD-1001")))
    assert check.passed


def test_must_not_call_fails_on_an_attempt_even_if_the_tool_refused():
    [check] = check_must_not_call(
        _task(must_not_call=["cancel_order"]),
        make_transcript(call(1, "cancel_order", is_error=True, order_id="ORD-2006")))
    assert not check.passed and "(error)" in check.detail


def test_must_not_call_kind_covers_every_write_tool():
    [check] = check_must_not_call(_task(must_not_call=["@write"]),
                                  make_transcript(call(1, "create_return", order_id="ORD-2007")))
    assert not check.passed and "create_return" in check.detail


# --- order ---------------------------------------------------------------------------

REFUND_ORDER = _task(order=[{"first": ["get_shipment"], "then": "issue_refund"}])


def test_order_passes_when_the_check_came_in_an_earlier_turn():
    [check] = check_order(REFUND_ORDER, make_transcript(
        call(1, "get_shipment", order_id="ORD-1002"), call(2, "issue_refund", order_id="ORD-1002")))
    assert check.passed


def test_order_fails_when_both_were_in_the_same_batch():
    [check] = check_order(REFUND_ORDER, make_transcript(
        call(1, "get_shipment", order_id="ORD-1002"), call(1, "issue_refund", order_id="ORD-1002")))
    assert not check.passed and "same batch" in check.detail


def test_order_fails_when_the_check_failed():
    [check] = check_order(REFUND_ORDER, make_transcript(
        call(1, "get_shipment", is_error=True, order_id="X"),
        call(2, "issue_refund", order_id="ORD-1002")))
    assert not check.passed


def test_order_is_not_violated_when_the_action_never_happened():
    [check] = check_order(REFUND_ORDER, make_transcript(call(1, "get_shipment", order_id="X")))
    assert check.passed and "not called" in check.detail


# --- the combined verdict ------------------------------------------------------------

FULL_TASK = make_task(
    expected={"disposition": "resolved",
              "db_change": {"refunds": {"insert": [{"order_id": "ORD-1002"}]}},
              "reply": {"facts": [["79.99"]]}},
    trajectory={"must_call": ["issue_refund"], "must_not_call": ["create_return"],
                "order": [{"first": ["get_shipment"], "then": "issue_refund"}]},
)
GOOD = make_transcript(call(1, "get_shipment", order_id="ORD-1002"),
                       call(2, "issue_refund", order_id="ORD-1002"),
                       reply="Refunded $79.99.", db_diff=inserted("refunds", refund_row()))


def test_success_needs_every_check():
    verdict = grade(FULL_TASK, GOOD)
    assert verdict.success is True
    assert all(verdict.group_passed(g) for g in ("db", "facts", "hygiene", "trajectory"))


def test_right_end_state_with_an_unverified_path_fails():
    lucky = make_transcript(call(1, "issue_refund", order_id="ORD-1002"),
                            reply="Refunded $79.99.", db_diff=inserted("refunds", refund_row()))
    verdict = grade(FULL_TASK, lucky)
    assert verdict.success is False
    assert verdict.group_passed("db") and not verdict.group_passed("trajectory")


def test_a_false_claim_with_no_action_fails_on_db():
    # Phase 1's failure mode: the reply says it was done, the store says it was not.
    claim = make_transcript(call(1, "get_shipment", order_id="ORD-1002"),
                            reply="I've refunded $79.99.")
    verdict = grade(FULL_TASK, claim)
    assert verdict.success is False and not verdict.group_passed("db")
    assert verdict.group_passed("facts")


def test_error_trial_is_not_graded_as_success_or_failure():
    verdict = grade(FULL_TASK, make_transcript(error="APIConnectionError: down"))
    assert verdict.success is None and verdict.group_passed("db") is None


def test_grade_refuses_a_transcript_for_another_task():
    import pytest

    with pytest.raises(ValueError):
        grade(FULL_TASK, make_transcript(task_id="other"))
