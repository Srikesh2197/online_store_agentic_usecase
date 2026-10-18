import json

from arl.env.tools import MAX_ORDERS, execute_tool


def call(conn, name, **arguments):
    return execute_tool(conn, name, json.dumps(arguments))


# find_customer
def test_find_customer_found(conn):
    result = call(conn, "find_customer", email="maya.chen@example.com")
    assert result == {
        "customer": {"id": "CUS-0001", "name": "Maya Chen", "email": "maya.chen@example.com"}
    }


def test_find_customer_ignores_case_and_spaces(conn):
    assert call(conn, "find_customer", email="  Maya.Chen@Example.com ")["customer"]["id"] == (
        "CUS-0001"
    )


def test_find_customer_not_found(conn):
    result = call(conn, "find_customer", email="nobody@example.com")
    assert result["error"] == "customer_not_found"
    assert "nobody@example.com" in result["message"]


# get_order
def test_get_order_found(conn):
    order = call(conn, "get_order", order_id="ORD-1001")["order"]
    assert order["status"] == "shipped"
    assert order["total_usd"] == "114.00"
    assert [i["name"] for i in order["items"]] == ["Trail running shoes", "Wool socks 3-pack"]
    assert order["refunds"] == []
    assert "shipping_address" not in order


def test_get_order_includes_refunds(conn):
    refunds = call(conn, "get_order", order_id="ORD-1004")["order"]["refunds"]
    assert refunds[0]["id"] == "REF-9001"
    assert refunds[0]["amount_usd"] == "24.00"


def test_get_order_not_found(conn):
    assert call(conn, "get_order", order_id="ORD-0000")["error"] == "order_not_found"


# list_orders
def test_list_orders_found_newest_first(conn):
    result = call(conn, "list_orders", customer_id="CUS-0001", limit=None)
    assert result["total_orders"] == 2
    assert [o["id"] for o in result["orders"]] == ["ORD-1001", "ORD-1002"]


def test_list_orders_respects_limit(conn):
    result = call(conn, "list_orders", customer_id="CUS-0001", limit=1)
    assert [o["id"] for o in result["orders"]] == ["ORD-1001"]
    assert result["total_orders"] == 2


def test_list_orders_caps_limit(conn):
    result = call(conn, "list_orders", customer_id="CUS-0001", limit=10_000)
    assert len(result["orders"]) <= MAX_ORDERS


def test_list_orders_customer_not_found(conn):
    result = call(conn, "list_orders", customer_id="maya.chen@example.com", limit=None)
    assert result["error"] == "customer_not_found"
    assert "find_customer" in result["message"]


# get_shipment
def test_get_shipment_found(conn):
    shipment = call(conn, "get_shipment", order_id="ORD-1001")["shipment"]
    assert shipment["tracking_number"] == "1Z999AA10123456784"
    assert shipment["status"] == "in_transit"
    assert shipment["delivered_at"] is None


def test_get_shipment_order_not_found(conn):
    assert call(conn, "get_shipment", order_id="ORD-0000")["error"] == "order_not_found"


def test_get_shipment_order_not_shipped(conn):
    result = call(conn, "get_shipment", order_id="ORD-1003")
    assert result["error"] == "no_shipment"
    assert "processing" in result["message"]


# execute_tool: bad calls come back as results, never as exceptions
def test_unknown_tool(conn):
    assert execute_tool(conn, "issue_refund", "{}")["error"] == "unknown_tool"


def test_arguments_not_json(conn):
    assert execute_tool(conn, "get_order", "{order_id:")["error"] == "invalid_arguments"


def test_arguments_fail_validation(conn):
    missing = execute_tool(conn, "get_order", "{}")
    assert missing["error"] == "invalid_arguments"
    assert "order_id" in missing["message"]
    extra = call(conn, "get_order", order_id="ORD-1001", verbose=True)
    assert extra["error"] == "invalid_arguments"


def test_results_are_json_serialisable(conn):
    for name, arguments in [
        ("find_customer", {"email": "maya.chen@example.com"}),
        ("get_order", {"order_id": "ORD-1004"}),
        ("list_orders", {"customer_id": "CUS-0001", "limit": None}),
        ("get_shipment", {"order_id": "ORD-1002"}),
    ]:
        json.dumps(call(conn, name, **arguments))
