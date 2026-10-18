"""The read tools, and the schemas that describe them to the model.

A tool has two halves:
- the schema and description, which are all the model ever sees of it;
- the Python function, which only our code runs.

Tools never raise to the caller. A failed lookup returns {"error": ..., "message": ...},
because the model can only react to what it reads in the result.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arl.env.store import dollars

MAX_ORDERS = 20
DEFAULT_ORDERS = 5


# --- Argument models -------------------------------------------------------------

class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindCustomerArgs(_Args):
    email: str = Field(description="The customer's email address, e.g. maya.chen@example.com")


class GetOrderArgs(_Args):
    order_id: str = Field(description="The order ID, e.g. ORD-1001")


class ListOrdersArgs(_Args):
    customer_id: str = Field(
        description="The customer ID returned by find_customer, e.g. CUS-0001. Not an email."
    )
    limit: int | None = Field(
        default=None,
        description=f"How many orders to return, newest first. Null means {DEFAULT_ORDERS}. "
        f"The maximum is {MAX_ORDERS}.",
    )


class GetShipmentArgs(_Args):
    order_id: str = Field(description="The order ID the shipment belongs to, e.g. ORD-1001")


# --- Implementations ---------------------------------------------------------------

def _error(code: str, message: str) -> dict:
    return {"error": code, "message": message}


def find_customer(conn: sqlite3.Connection, args: FindCustomerArgs) -> dict:
    row = conn.execute(
        "SELECT id, name, email FROM customers WHERE email = ?", (args.email.strip().lower(),)
    ).fetchone()
    if row is None:
        return _error(
            "customer_not_found",
            f"No customer has the email '{args.email}'. Ask the customer to check the address "
            "they used at checkout.",
        )
    return {"customer": dict(row)}


def get_order(conn: sqlite3.Connection, args: GetOrderArgs) -> dict:
    order_id = args.order_id.strip().upper()
    order = conn.execute(
        "SELECT id, customer_id, status, placed_at, total_cents FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        return _error(
            "order_not_found",
            f"No order has the ID '{args.order_id}'. Order IDs look like ORD-1001.",
        )
    items = conn.execute(
        "SELECT sku, name, quantity, unit_price_cents FROM items WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()
    refunds = conn.execute(
        "SELECT id, amount_cents, reason, status, created_at FROM refunds WHERE order_id = ? "
        "ORDER BY id",
        (order_id,),
    ).fetchall()
    return {
        "order": {
            "id": order["id"],
            "customer_id": order["customer_id"],
            "status": order["status"],
            "placed_at": order["placed_at"],
            "total_usd": dollars(order["total_cents"]),
            "items": [
                {"sku": i["sku"], "name": i["name"], "quantity": i["quantity"],
                 "unit_price_usd": dollars(i["unit_price_cents"])}
                for i in items
            ],
            "refunds": [
                {"id": r["id"], "amount_usd": dollars(r["amount_cents"]), "reason": r["reason"],
                 "status": r["status"], "created_at": r["created_at"]}
                for r in refunds
            ],
        }
    }


def list_orders(conn: sqlite3.Connection, args: ListOrdersArgs) -> dict:
    customer_id = args.customer_id.strip().upper()
    if conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is None:
        return _error(
            "customer_not_found",
            f"No customer has the ID '{args.customer_id}'. Customer IDs look like CUS-0001; "
            "use find_customer to get one from an email.",
        )
    limit = max(1, min(args.limit or DEFAULT_ORDERS, MAX_ORDERS))
    rows = conn.execute(
        "SELECT id, status, placed_at, total_cents FROM orders WHERE customer_id = ? "
        "ORDER BY placed_at DESC, id DESC",
        (customer_id,),
    ).fetchall()
    return {
        "customer_id": customer_id,
        "total_orders": len(rows),
        "orders": [
            {"id": r["id"], "status": r["status"], "placed_at": r["placed_at"],
             "total_usd": dollars(r["total_cents"])}
            for r in rows[:limit]
        ],
    }


def get_shipment(conn: sqlite3.Connection, args: GetShipmentArgs) -> dict:
    order_id = args.order_id.strip().upper()
    order = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return _error(
            "order_not_found",
            f"No order has the ID '{args.order_id}'. Order IDs look like ORD-1001.",
        )
    row = conn.execute(
        "SELECT id, order_id, carrier, tracking_number, status, shipped_at, estimated_delivery, "
        "delivered_at FROM shipments WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if row is None:
        return _error(
            "no_shipment",
            f"Order {order_id} has no shipment yet. Its order status is '{order['status']}'.",
        )
    return {"shipment": dict(row)}


# --- Registry ----------------------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[sqlite3.Connection, BaseModel], dict]


TOOLS = [
    Tool(
        "find_customer",
        "Find a customer by email address. Returns the customer's ID, name and email. "
        "Use this when the customer gives an email and you need their customer ID, for example "
        "before list_orders. Do not use it when you already have an order ID.",
        FindCustomerArgs,
        find_customer,
    ),
    Tool(
        "get_order",
        "Get one order by its order ID: status, date placed, total, line items and any refunds. "
        "Use this when you have an order ID. It does not return tracking details; use "
        "get_shipment for those.",
        GetOrderArgs,
        get_order,
    ),
    Tool(
        "list_orders",
        "List a customer's orders, newest first, with status, date and total for each. "
        "Needs a customer ID, not an email. Use this when the customer has not given an order ID "
        "or asks about their orders in general. It does not return line items.",
        ListOrdersArgs,
        list_orders,
    ),
    Tool(
        "get_shipment",
        "Get the shipment for an order: carrier, tracking number, shipment status, ship date and "
        "estimated or actual delivery date. Use this for questions about where an order is or "
        "when it will arrive. An order that has not shipped has no shipment.",
        GetShipmentArgs,
        get_shipment,
    ),
]
_BY_NAME = {tool.name: tool for tool in TOOLS}


# --- Schemas -----------------------------------------------------------------------

# Written by hand once, so the wire format is visible. The others are generated from
# the Pydantic models; a test checks that generating this one gives the same result.
FIND_CUSTOMER_SCHEMA = {
    "type": "function",
    "name": "find_customer",
    "description": _BY_NAME["find_customer"].description,
    "parameters": {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "The customer's email address, e.g. maya.chen@example.com",
            }
        },
        "required": ["email"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _to_strict(schema: dict) -> dict:
    """Reshape a Pydantic JSON schema into what OpenAI strict mode accepts.

    Strict mode requires every property to be listed in `required` (an optional field
    is expressed as nullable instead) and `additionalProperties: false` on every object.
    Pydantic's `title` and `default` annotations are dropped.
    """
    out = {k: v for k, v in schema.items() if k not in ("title", "default")}
    if "properties" in out:
        out["properties"] = {name: _to_strict(sub) for name, sub in out["properties"].items()}
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    if "anyOf" in out:
        out["anyOf"] = [_to_strict(sub) for sub in out["anyOf"]]
    if isinstance(out.get("items"), dict):
        out["items"] = _to_strict(out["items"])
    return out


def generate_schema(tool: Tool) -> dict:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": _to_strict(tool.args_model.model_json_schema()),
        "strict": True,
    }


def tool_schemas() -> list[dict]:
    """The `tools` array sent to the model."""
    return [
        FIND_CUSTOMER_SCHEMA if tool.name == "find_customer" else generate_schema(tool)
        for tool in TOOLS
    ]


# --- Execution ---------------------------------------------------------------------

def execute_tool(conn: sqlite3.Connection, name: str, arguments: str) -> dict:
    """Run one tool call. `arguments` is the JSON string exactly as the model sent it."""
    tool = _BY_NAME.get(name)
    if tool is None:
        return _error("unknown_tool", f"There is no tool named '{name}'.")
    try:
        args = tool.args_model.model_validate(json.loads(arguments))
    except json.JSONDecodeError as exc:
        return _error("invalid_arguments", f"The arguments are not valid JSON: {exc.msg}.")
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
            for e in exc.errors()
        )
        return _error("invalid_arguments", f"The arguments do not match the schema. {problems}")
    return tool.fn(conn, args)
