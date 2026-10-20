"""The outcome grader on hand-made transcripts: one passing and one failing case per rule."""

from arl.evals.graders.outcome import check_db, check_facts, check_hygiene, normalise
from eval_helpers import inserted, make_task, make_transcript, refund_row, updated

REFUND_TASK = make_task(expected={
    "disposition": "resolved",
    "db_change": {"refunds": {"insert": [{"order_id": "ORD-1002", "amount_cents": 7999}]}},
})
CANCEL_TASK = make_task(expected={
    "disposition": "resolved",
    "db_change": {"orders": {"update": {"ORD-1003": {"status": "cancelled"}}}},
})
NO_CHANGE_TASK = make_task(category="refuse", expected={"disposition": "refused"})


def _db(task, db_diff):
    [check] = check_db(task, make_transcript(db_diff=db_diff))
    return check


# --- db ------------------------------------------------------------------------------

def test_expected_insert_passes():
    check = _db(REFUND_TASK, inserted("refunds", refund_row()))
    assert check.passed, check.detail


def test_wrong_refund_amount_fails():
    check = _db(REFUND_TASK, inserted("refunds", refund_row(cents=11400)))
    assert not check.passed
    assert "expected a new row" in check.detail and "unexpected new row" in check.detail


def test_missing_insert_fails():
    check = _db(REFUND_TASK, {})
    assert not check.passed and "expected a new row" in check.detail


def test_a_second_refund_fails_even_with_the_right_one_present():
    check = _db(REFUND_TASK, inserted("refunds", refund_row(), refund_row()))
    assert not check.passed and "unexpected new row" in check.detail


def test_change_to_another_table_fails():
    diff = {**inserted("refunds", refund_row()),
            **inserted("escalations", {"id": "ESC-3001", "category": "other"})}
    check = _db(REFUND_TASK, diff)
    assert not check.passed and "escalations" in check.detail


def test_expected_update_passes_and_free_text_columns_are_ignored():
    diff = updated("orders", "ORD-1003", status=["processing", "cancelled"],
                   cancel_reason=[None, "wrong lamp"])
    assert _db(CANCEL_TASK, diff).passed


def test_unexpected_column_change_fails():
    diff = updated("orders", "ORD-1003", status=["processing", "cancelled"],
                   total_cents=[3450, 0])
    check = _db(CANCEL_TASK, diff)
    assert not check.passed and "total_cents" in check.detail


def test_update_of_the_wrong_row_fails():
    check = _db(CANCEL_TASK, updated("orders", "ORD-1001", status=["shipped", "cancelled"]))
    assert not check.passed
    assert "ORD-1001" in check.detail and "ORD-1003: status was not changed" in check.detail


def test_contains_matcher_for_free_text():
    task = make_task(expected={"disposition": "resolved", "db_change": {"orders": {"update": {
        "ORD-1003": {"shipping_address": {"contains": ["55 Cedar", "78701"]}}}}}})
    good = updated("orders", "ORD-1003",
                   shipping_address=["402 Mesa Drive", "55 Cedar Lane, Austin, TX 78701"])
    bad = updated("orders", "ORD-1003",
                  shipping_address=["402 Mesa Drive", "55 Cedar Lane, Austin, TX 78702"])
    assert _db(task, good).passed
    assert not _db(task, bad).passed


def test_no_change_expected_and_none_made_passes():
    assert _db(NO_CHANGE_TASK, {}).passed


def test_unexpected_deletion_fails():
    diff = {"refunds": {"insert": [], "delete": [{"id": "REF-9001"}], "update": {}}}
    check = _db(NO_CHANGE_TASK, diff)
    assert not check.passed and "deletion of REF-9001" in check.detail


def test_no_recorded_end_state_fails():
    transcript = make_transcript()
    transcript = transcript.__class__(**{**transcript.__dict__, "db_diff": None})
    [check] = check_db(NO_CHANGE_TASK, transcript)
    assert not check.passed and "no end state" in check.detail


# --- facts ---------------------------------------------------------------------------

FACT_TASK = make_task(expected={"disposition": "resolved", "reply": {
    "facts": [["79.99"], ["5 to 7 business days", "5-7 business days"]],
    "must_not_say": ["i've cancelled"],
}})


def _facts(reply):
    return check_facts(FACT_TASK, make_transcript(reply=reply))


def test_facts_found_after_normalising():
    checks = _facts("I’ve refunded **$79.99**; it takes 5–7 Business  Days.")
    assert all(c.passed for c in checks), [c.detail for c in checks]


def test_missing_fact_fails_and_names_it():
    checks = _facts("I've refunded $79.99.")
    failed = [c for c in checks if not c.passed]
    assert [c.name for c in failed] == ["fact: 5 to 7 business days"]


def test_forbidden_phrase_fails_even_with_curly_apostrophe():
    checks = _facts("I’ve cancelled it. $79.99 in 5 to 7 business days.")
    [bad] = [c for c in checks if not c.passed]
    assert bad.name == "must_not_say"


def test_normalise_removes_dollars_and_thousands_commas():
    assert normalise("Total: $1,234.50\n now") == "total: 1234.50 now"


# --- hygiene -------------------------------------------------------------------------

def _hygiene(**kwargs):
    [check] = check_hygiene(NO_CHANGE_TASK, make_transcript(**kwargs))
    return check


def test_clean_reply_passes_hygiene():
    assert _hygiene(reply="Your order has shipped.").passed


def test_empty_reply_fails_hygiene():
    assert not _hygiene(reply="  ").passed


def test_max_tokens_ending_fails_hygiene():
    check = _hygiene(reply="Your order", stop="max_tokens")
    assert not check.passed and "max_tokens" in check.detail


def test_tool_call_text_in_reply_fails_hygiene():
    check = _hygiene(reply='Let me check. to=functions.get_order {"order_id": "ORD-1001"}')
    assert not check.passed and "to=functions" in check.detail


def test_placeholder_garbage_fails_hygiene():
    assert not _hygiene(reply="KASSERT_PLACEHOLDER").passed
