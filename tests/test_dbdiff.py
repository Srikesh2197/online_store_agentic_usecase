"""The database diff, against real tool calls on a fresh store."""

import json

from arl.env.tools import execute_tool
from arl.evals.dbdiff import diff, snapshot


def test_untouched_store_has_no_diff(conn):
    assert diff(snapshot(conn), snapshot(conn)) == {}


def test_reads_change_nothing(conn):
    before = snapshot(conn)
    execute_tool(conn, "get_order", json.dumps({"order_id": "ORD-1001"}))
    assert diff(before, snapshot(conn)) == {}


def test_refund_is_one_insert(conn):
    before = snapshot(conn)
    execute_tool(conn, "issue_refund", json.dumps(
        {"order_id": "ORD-1002", "amount_usd": "79.99", "reason": "cracked"}))
    changes = diff(before, snapshot(conn))
    assert list(changes) == ["refunds"]
    [row] = changes["refunds"]["insert"]
    assert (row["order_id"], row["amount_cents"]) == ("ORD-1002", 7999)
    assert changes["refunds"]["delete"] == [] and changes["refunds"]["update"] == {}


def test_cancel_is_an_update_with_old_and_new_values(conn):
    before = snapshot(conn)
    execute_tool(conn, "cancel_order", json.dumps({"order_id": "ORD-1003", "reason": "wrong"}))
    changes = diff(before, snapshot(conn))
    assert changes == {"orders": {"insert": [], "delete": [], "update": {
        "ORD-1003": {"status": ["processing", "cancelled"], "cancel_reason": [None, "wrong"]}}}}


def test_deletion_is_reported(conn):
    before = snapshot(conn)
    conn.execute("DELETE FROM refunds WHERE id = 'REF-9001'")
    assert [r["id"] for r in diff(before, snapshot(conn))["refunds"]["delete"]] == ["REF-9001"]


def test_diff_is_plain_json(conn):
    before = snapshot(conn)
    execute_tool(conn, "escalate_to_human", json.dumps(
        {"category": "other", "summary": "s", "order_id": None, "customer_id": None}))
    changes = diff(before, snapshot(conn))
    assert json.loads(json.dumps(changes)) == changes
