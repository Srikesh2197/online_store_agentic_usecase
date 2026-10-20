"""The new read tool, the write tools and escalation. Each test checks the database."""

import json

from arl.env.tools import TOOLS, execute_tool


def call(conn, name, **arguments):
    return execute_tool(conn, name, json.dumps(arguments))


def one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()


def test_tool_counts_by_kind():
    kinds = [tool.kind for tool in TOOLS]
    assert (kinds.count("read"), kinds.count("write"), kinds.count("escalate")) == (5, 4, 1)


# get_customer
def test_get_customer(conn):
    customer = call(conn, "get_customer", customer_id="cus-0001")["customer"]
    assert customer == {"id": "CUS-0001", "name": "Maya Chen", "email": "maya.chen@example.com",
                        "member_since": "2025-03-14", "total_orders": 2}


def test_get_customer_not_found(conn):
    result = call(conn, "get_customer", customer_id="maya.chen@example.com")
    assert result["error"] == "customer_not_found"
    assert "find_customer" in result["message"]


# issue_refund
def test_issue_refund_writes_a_row(conn):
    result = call(conn, "issue_refund", order_id="ORD-1002", amount_usd="79.99",
                  reason="Jug arrived cracked")
    assert result["refund"]["id"] == "REF-9002"
    assert result["refund"]["amount_usd"] == "79.99"
    assert (result["order_total_usd"], result["refunded_to_date_usd"]) == ("79.99", "79.99")
    row = one(conn, "SELECT order_id, amount_cents, status FROM refunds WHERE id = 'REF-9002'")
    assert tuple(row) == ("ORD-1002", 7999, "issued")


def test_issue_refund_reports_earlier_refunds(conn):
    result = call(conn, "issue_refund", order_id="ORD-1004", amount_usd="10.00", reason="x")
    assert result["refunded_to_date_usd"] == "34.00"


def test_issue_refund_does_not_enforce_policy_limits(conn):
    # More than the order total is a policy violation, left to the model in this stage.
    result = call(conn, "issue_refund", order_id="ORD-1002", amount_usd="500.00", reason="x")
    assert "refund" in result


def test_issue_refund_bad_amount_format(conn):
    result = call(conn, "issue_refund", order_id="ORD-1002", amount_usd="$79.99", reason="x")
    assert result["error"] == "invalid_arguments"
    assert "e.g. 79.99" in result["message"]
    assert one(conn, "SELECT COUNT(*) FROM refunds")[0] == 1


def test_issue_refund_zero(conn):
    result = call(conn, "issue_refund", order_id="ORD-1002", amount_usd="0.00", reason="x")
    assert result["error"] == "invalid_amount"


def test_issue_refund_unknown_order(conn):
    result = call(conn, "issue_refund", order_id="ORD-0000", amount_usd="1.00", reason="x")
    assert result["error"] == "order_not_found"
    assert "Nothing was changed" in result["message"]


def test_issue_refund_cancelled_order(conn):
    call(conn, "cancel_order", order_id="ORD-1003", reason="x")
    result = call(conn, "issue_refund", order_id="ORD-1003", amount_usd="1.00", reason="x")
    assert result["error"] == "order_cancelled"


# cancel_order
def test_cancel_order(conn):
    result = call(conn, "cancel_order", order_id="ord-1003", reason="Ordered the wrong lamp")
    assert result["order"] == {"id": "ORD-1003", "status": "cancelled",
                               "previous_status": "processing"}
    row = one(conn, "SELECT status, cancel_reason FROM orders WHERE id = 'ORD-1003'")
    assert tuple(row) == ("cancelled", "Ordered the wrong lamp")


def test_cancel_order_twice(conn):
    call(conn, "cancel_order", order_id="ORD-1003", reason="x")
    assert call(conn, "cancel_order", order_id="ORD-1003", reason="x")["error"] == (
        "already_cancelled"
    )


def test_cancel_order_does_not_enforce_the_processing_rule(conn):
    # Cancelling a shipped order breaks the policy, but the tool leaves that to the model.
    assert call(conn, "cancel_order", order_id="ORD-1001", reason="x")["order"][
        "previous_status"] == "shipped"


# update_shipping_address
ADDRESS = {"street": "55 Cedar Lane", "city": "Austin", "state": "TX", "postal_code": "78701"}


def test_update_shipping_address(conn):
    result = call(conn, "update_shipping_address", order_id="ORD-1003", **ADDRESS)
    assert result["order"] == {"id": "ORD-1003", "status": "processing"}
    assert "Cedar" not in json.dumps(result)
    assert one(conn, "SELECT shipping_address FROM orders WHERE id = 'ORD-1003'")[0] == (
        "55 Cedar Lane, Austin, TX 78701"
    )


def test_update_shipping_address_bad_postal_code(conn):
    result = call(conn, "update_shipping_address", order_id="ORD-1003",
                  **{**ADDRESS, "postal_code": "7870"})
    assert result["error"] == "invalid_arguments"
    assert "postal_code" in result["message"] and "e.g. 78701" in result["message"]
    assert one(conn, "SELECT shipping_address FROM orders WHERE id = 'ORD-1003'")[0] == (
        "402 Mesa Drive, Austin, TX 78704"
    )


def test_update_shipping_address_bad_state(conn):
    result = call(conn, "update_shipping_address", order_id="ORD-1003",
                  **{**ADDRESS, "state": "Texas"})
    assert "state" in result["message"]


# create_return
def test_create_return(conn):
    result = call(conn, "create_return", order_id="ORD-1001", sku="sock-wl-3p", quantity=2,
                  condition="unopened", reason="Wrong size")
    assert result["return"]["id"] == "RMA-7001"
    assert "do not issue it yourself" in result["note"]
    row = one(conn, "SELECT sku, quantity, condition, status FROM returns")
    assert tuple(row) == ("SOCK-WL-3P", 2, "unopened", "authorized")


def test_create_return_unknown_sku_lists_valid_ones(conn):
    result = call(conn, "create_return", order_id="ORD-1001", sku="BLND-CT-01", quantity=1,
                  condition="opened", reason="x")
    assert result["error"] == "sku_not_in_order"
    assert "SHOE-TR-42, SOCK-WL-3P" in result["message"]


def test_create_return_quantity_counts_earlier_returns(conn):
    call(conn, "create_return", order_id="ORD-1001", sku="SOCK-WL-3P", quantity=1,
         condition="unopened", reason="x")
    result = call(conn, "create_return", order_id="ORD-1001", sku="SOCK-WL-3P", quantity=2,
                  condition="unopened", reason="x")
    assert result["error"] == "quantity_too_high"
    assert "at most 1" in result["message"]


def test_create_return_quantity_below_one(conn):
    result = call(conn, "create_return", order_id="ORD-1001", sku="SOCK-WL-3P", quantity=0,
                  condition="unopened", reason="x")
    assert result["error"] == "invalid_arguments"
    assert "quantity" in result["message"]


def test_create_return_bad_condition(conn):
    result = call(conn, "create_return", order_id="ORD-1001", sku="SOCK-WL-3P", quantity=1,
                  condition="broken", reason="x")
    assert result["error"] == "invalid_arguments"


# escalate_to_human
def test_escalate(conn):
    result = call(conn, "escalate_to_human", category="policy_exception",
                  summary="Kettle failed after 46 days.", order_id="ORD-1004", customer_id=None)
    assert result["escalation"] == {"id": "ESC-3001", "category": "policy_exception",
                                    "status": "open"}
    row = one(conn, "SELECT order_id, customer_id, status FROM escalations")
    assert tuple(row) == ("ORD-1004", None, "open")


def test_escalate_with_unknown_order_says_to_pass_null(conn):
    result = call(conn, "escalate_to_human", category="other", summary="x",
                  order_id="ORD-0000", customer_id=None)
    assert result["error"] == "order_not_found"
    assert "null" in result["message"]
    assert one(conn, "SELECT COUNT(*) FROM escalations")[0] == 0


def test_every_write_leaves_a_fresh_store_untouched(conn):
    from arl.env.seed import new_store

    call(conn, "cancel_order", order_id="ORD-1003", reason="x")
    assert one(new_store(), "SELECT status FROM orders WHERE id = 'ORD-1003'")[0] == "processing"
