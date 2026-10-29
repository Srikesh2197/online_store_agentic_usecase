"""The tools: five read, four write, one escalate. And the schemas that describe them.

A tool has two halves:
- the schema and description, which are all the model ever sees of it;
- the Python function, which only our code runs.

Tools never raise to the caller. A failed call returns {"error": ..., "message": ...},
because the model can only react to what it reads in the result. Each message says what
went wrong and what to do instead.

Write tools validate their own input: the shape of the arguments, that the records exist,
and states the data cannot represent (cancelling a cancelled order, returning a SKU that
is not in the order). They do not enforce the support policy (the 30-day window, refund
limits, who may change an order). Those rules are in policy.md, for the model to follow.

Stage 5 adds three things, all switched by the trial's environment (`conn.env`), so with the
default environment the tools behave exactly as before:
- the exact part of the policy, enforced inside the write tools (env/invariants.py);
- injected backend faults (env/faults.py), raised from execute_tool;
- idempotency keys: a write retried with the same key returns the first result and writes
  nothing.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arl.env import invariants
from arl.env.faults import raise_fault
from arl.env.seed import SIM_TODAY
from arl.env.store import dollars, env_of
from arl.llm.types import ToolSpec

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


class GetCustomerArgs(_Args):
    customer_id: str = Field(description="The customer ID, e.g. CUS-0001")


class IssueRefundArgs(_Args):
    order_id: str = Field(description="The order ID to refund, e.g. ORD-1002")
    amount_usd: str = Field(
        pattern=r"^\d+\.\d{2}$",
        description="The amount to refund in US dollars, with exactly two decimals, e.g. 79.99",
    )
    reason: str = Field(description="Why the refund is issued, in one sentence")


class CancelOrderArgs(_Args):
    order_id: str = Field(description="The order ID to cancel, e.g. ORD-1003")
    reason: str = Field(description="Why the customer wants to cancel, in one sentence")


class UpdateShippingAddressArgs(_Args):
    order_id: str = Field(description="The order ID whose delivery address changes, e.g. ORD-1003")
    street: str = Field(description="Street number and name, e.g. 55 Cedar Lane")
    city: str = Field(description="City, e.g. Austin")
    state: str = Field(pattern=r"^[A-Z]{2}$",
                       description="Two-letter US state code in capitals, e.g. TX")
    postal_code: str = Field(pattern=r"^\d{5}$", description="Five-digit US ZIP code, e.g. 78701")


class CreateReturnArgs(_Args):
    order_id: str = Field(description="The order ID the item came from, e.g. ORD-1002")
    sku: str = Field(description="The SKU of the item being returned, from get_order")
    quantity: int = Field(ge=1, description="How many of that item are being returned")
    condition: Literal["unopened", "opened", "damaged"] = Field(
        description="The item's condition as the customer describes it"
    )
    reason: str = Field(description="Why the customer is returning it, in one sentence")


class EscalateArgs(_Args):
    category: Literal["policy_exception", "cannot_verify", "complaint", "other"] = Field(
        description="policy_exception: the request is outside the policy; cannot_verify: you "
        "cannot confirm who the customer is or which order they mean; complaint: the customer "
        "wants a person; other: anything else you cannot resolve with the tools"
    )
    summary: str = Field(
        description="What the customer wants, what you found, and why you are escalating, "
        "in two or three sentences, for the person who picks this up"
    )
    order_id: str | None = Field(default=None, description="The order ID concerned, or null")
    customer_id: str | None = Field(default=None, description="The customer ID, or null")


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
    notes = conn.execute(
        "SELECT source, body, created_at FROM order_notes WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()
    result = {
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
    if notes:   # only when there are any, so results for orders without notes are unchanged
        result["order"]["notes"] = [dict(n) for n in notes]
    return result


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


def get_customer(conn: sqlite3.Connection, args: GetCustomerArgs) -> dict:
    customer_id = args.customer_id.strip().upper()
    row = conn.execute(
        "SELECT c.id, c.name, c.email, c.created_at AS member_since, COUNT(o.id) AS total_orders "
        "FROM customers c LEFT JOIN orders o ON o.customer_id = c.id WHERE c.id = ? GROUP BY c.id",
        (customer_id,),
    ).fetchone()
    if row is None:
        return _error(
            "customer_not_found",
            f"No customer has the ID '{args.customer_id}'. Customer IDs look like CUS-0001; "
            "use find_customer to get one from an email.",
        )
    return {"customer": dict(row)}


# --- Write tools -------------------------------------------------------------------

def _find_order(conn: sqlite3.Connection, order_id: str):
    return conn.execute(
        "SELECT id, customer_id, status, total_cents FROM orders WHERE id = ?",
        (order_id.strip().upper(),),
    ).fetchone()


def _order_not_found(order_id: str) -> dict:
    return _error(
        "order_not_found",
        f"No order has the ID '{order_id}'. Order IDs look like ORD-1001. Nothing was changed.",
    )


def _order_cancelled(order_id: str, action: str) -> dict:
    return _error(
        "order_cancelled",
        f"Order {order_id} is cancelled, so it cannot {action}. Nothing was changed.",
    )


def _next_id(conn: sqlite3.Connection, table: str, prefix: str, first: int) -> str:
    rows = conn.execute(f"SELECT id FROM {table}").fetchall()
    numbers = [int(row["id"].split("-")[1]) for row in rows]
    return f"{prefix}-{max(numbers, default=first - 1) + 1}"


def issue_refund(conn: sqlite3.Connection, args: IssueRefundArgs) -> dict:
    order = _find_order(conn, args.order_id)
    if order is None:
        return _order_not_found(args.order_id)
    if order["status"] == "cancelled":
        return _order_cancelled(order["id"], "be refunded")
    cents = round(float(args.amount_usd) * 100)
    if cents <= 0:
        return _error("invalid_amount",
                      f"The refund amount must be more than 0.00; got {args.amount_usd}.")
    if problem := invariants.check(conn, "issue_refund", order, cents=cents):
        return problem
    refund_id = _next_id(conn, "refunds", "REF", 9001)
    conn.execute(
        "INSERT INTO refunds VALUES (?, ?, ?, ?, 'issued', ?)",
        (refund_id, order["id"], cents, args.reason, SIM_TODAY.isoformat()),
    )
    conn.commit()
    refunded = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?", (order["id"],)
    ).fetchone()[0]
    return {
        "refund": {"id": refund_id, "order_id": order["id"], "amount_usd": dollars(cents),
                   "reason": args.reason, "status": "issued",
                   "created_at": SIM_TODAY.isoformat()},
        "order_total_usd": dollars(order["total_cents"]),
        "refunded_to_date_usd": dollars(refunded),
        "note": "The refund goes to the original payment method and arrives in 5 to 7 "
                "business days.",
    }


def cancel_order(conn: sqlite3.Connection, args: CancelOrderArgs) -> dict:
    order = _find_order(conn, args.order_id)
    if order is None:
        return _order_not_found(args.order_id)
    if order["status"] == "cancelled":
        return _error("already_cancelled",
                      f"Order {order['id']} is already cancelled. Nothing was changed.")
    if problem := invariants.check(conn, "cancel_order", order):
        return problem
    conn.execute("UPDATE orders SET status = 'cancelled', cancel_reason = ? WHERE id = ?",
                 (args.reason, order["id"]))
    conn.commit()
    return {"order": {"id": order["id"], "status": "cancelled",
                      "previous_status": order["status"]},
            "note": "The order is cancelled."}


def update_shipping_address(conn: sqlite3.Connection, args: UpdateShippingAddressArgs) -> dict:
    order = _find_order(conn, args.order_id)
    if order is None:
        return _order_not_found(args.order_id)
    if order["status"] == "cancelled":
        return _order_cancelled(order["id"], "have its address changed")
    if problem := invariants.check(conn, "update_shipping_address", order):
        return problem
    address = f"{args.street.strip()}, {args.city.strip()}, {args.state} {args.postal_code}"
    conn.execute("UPDATE orders SET shipping_address = ? WHERE id = ?", (address, order["id"]))
    conn.commit()
    # The new address is not echoed back: results go into the transcript and the logs.
    return {"order": {"id": order["id"], "status": order["status"]},
            "note": "The shipping address is updated."}


def create_return(conn: sqlite3.Connection, args: CreateReturnArgs) -> dict:
    order = _find_order(conn, args.order_id)
    if order is None:
        return _order_not_found(args.order_id)
    if order["status"] == "cancelled":
        return _order_cancelled(order["id"], "have a return")
    if problem := invariants.check(conn, "create_return", order):
        return problem
    sku = args.sku.strip().upper()
    items = conn.execute(
        "SELECT sku, quantity FROM items WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()
    ordered = {item["sku"]: item["quantity"] for item in items}
    if sku not in ordered:
        return _error(
            "sku_not_in_order",
            f"Order {order['id']} has no item with SKU '{args.sku}'. Its SKUs are: "
            f"{', '.join(ordered)}. Nothing was changed.",
        )
    already = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM returns WHERE order_id = ? AND sku = ?",
        (order["id"], sku),
    ).fetchone()[0]
    if args.quantity > ordered[sku] - already:
        return _error(
            "quantity_too_high",
            f"Order {order['id']} has {ordered[sku]} of {sku} and {already} already returned, "
            f"so at most {ordered[sku] - already} can be returned; got {args.quantity}. "
            "Nothing was changed.",
        )
    return_id = _next_id(conn, "returns", "RMA", 7001)
    conn.execute(
        "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, 'authorized', ?)",
        (return_id, order["id"], sku, args.quantity, args.condition, args.reason,
         SIM_TODAY.isoformat()),
    )
    conn.commit()
    return {
        "return": {"id": return_id, "order_id": order["id"], "sku": sku,
                   "quantity": args.quantity, "condition": args.condition,
                   "status": "authorized"},
        "note": "A prepaid return label is emailed to the customer. The warehouse issues the "
                "refund when the item arrives; do not issue it yourself.",
    }


def escalate_to_human(conn: sqlite3.Connection, args: EscalateArgs) -> dict:
    order_id = args.order_id.strip().upper() if args.order_id else None
    customer_id = args.customer_id.strip().upper() if args.customer_id else None
    if order_id and _find_order(conn, order_id) is None:
        return _error("order_not_found",
                      f"No order has the ID '{args.order_id}'. Pass null for order_id if you "
                      "do not have a valid one. Nothing was escalated.")
    if customer_id and conn.execute(
        "SELECT 1 FROM customers WHERE id = ?", (customer_id,)
    ).fetchone() is None:
        return _error("customer_not_found",
                      f"No customer has the ID '{args.customer_id}'. Pass null for customer_id "
                      "if you do not have a valid one. Nothing was escalated.")
    escalation_id = _next_id(conn, "escalations", "ESC", 3001)
    conn.execute(
        "INSERT INTO escalations VALUES (?, ?, ?, ?, ?, 'open', ?)",
        (escalation_id, args.category, args.summary, order_id, customer_id,
         SIM_TODAY.isoformat()),
    )
    conn.commit()
    return {"escalation": {"id": escalation_id, "category": args.category, "status": "open"},
            "note": "A member of the support team will reply to the customer within one "
                    "business day."}


# --- Registry ----------------------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[sqlite3.Connection, BaseModel], dict]
    kind: Literal["read", "write", "escalate"] = "read"


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
        "Use this when you have an order ID. It does not return tracking details or the "
        "delivery date; for questions about where an order is or when it arrives, also call "
        "get_shipment.",
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
    Tool(
        "get_customer",
        "Get a customer by customer ID: name, email, member-since date and number of orders. "
        "Use this when you have a customer ID, for example the customer_id on an order, and "
        "need to know whose it is. It does not return addresses or payment details. To look a "
        "customer up by email, use find_customer instead.",
        GetCustomerArgs,
        get_customer,
    ),
    Tool(
        "issue_refund",
        "Refund money on an order to the original payment method. This changes the store and "
        "cannot be undone. Use it only when the policy allows a refund, for the amount the "
        "policy allows, after you have looked up the order. Do not use it for unopened items "
        "that are being sent back: create a return for those instead.",
        IssueRefundArgs,
        issue_refund,
        "write",
    ),
    Tool(
        "cancel_order",
        "Cancel an order. This changes the store and cannot be undone. Use it only when the "
        "customer asks to cancel and the policy allows it; check the order status with "
        "get_order first. Do not use it to stop a delivery that is already on its way.",
        CancelOrderArgs,
        cancel_order,
        "write",
    ),
    Tool(
        "update_shipping_address",
        "Change the delivery address of an order. This changes the store. Use it only when the "
        "customer gives a complete new address and the policy allows the change; check the "
        "order status with get_order first. The address is not repeated in the result.",
        UpdateShippingAddressArgs,
        update_shipping_address,
        "write",
    ),
    Tool(
        "create_return",
        "Authorise the return of an item from an order and email the customer a prepaid "
        "label. This changes the store. Use it when the policy allows a return; get the SKU "
        "from get_order. The refund for a returned item is issued by the warehouse when the "
        "item arrives, so do not also call issue_refund for it.",
        CreateReturnArgs,
        create_return,
        "write",
    ),
    Tool(
        "escalate_to_human",
        "Hand the ticket to a person on the support team. Use it when the request is outside "
        "the policy, when you cannot confirm who the customer is or which order they mean, or "
        "when the customer asks for a person. Tell the customer it has been escalated; do not "
        "also take the action yourself.",
        EscalateArgs,
        escalate_to_human,
        "escalate",
    ),
]
_BY_NAME = {tool.name: tool for tool in TOOLS}


# --- Schemas -----------------------------------------------------------------------

# Written by hand once, so the schema is visible. The others are generated from the
# Pydantic models; a test checks that generating this one gives the same result.
FIND_CUSTOMER_PARAMETERS = {
    "type": "object",
    "properties": {
        "email": {
            "type": "string",
            "description": "The customer's email address, e.g. maya.chen@example.com",
        }
    },
    "required": ["email"],
    "additionalProperties": False,
}

# Constraints Anthropic's strict mode rejects. They are moved into the description, so
# the model still reads them, and Pydantic still enforces them when the tool runs.
_CONSTRAINTS = {
    "minimum": "at least {}",
    "maximum": "at most {}",
    "exclusiveMinimum": "more than {}",
    "exclusiveMaximum": "less than {}",
    "minLength": "at least {} characters",
    "maxLength": "at most {} characters",
}


def _constraint_notes(schema: dict) -> list[str]:
    notes = [text.format(schema[key]) for key, text in _CONSTRAINTS.items() if key in schema]
    for sub in schema.get("anyOf", []):  # a nullable field keeps its constraints in a branch
        notes += _constraint_notes(sub)
    return notes


def _to_strict(schema: dict) -> dict:
    """Reshape a Pydantic JSON schema into what both providers' strict modes accept.

    OpenAI requires every property to be listed in `required` (an optional field is
    expressed as nullable instead) and `additionalProperties: false` on every object.
    Anthropic accepts that too, but rejects numeric and length constraints.
    Pydantic's `title` and `default` annotations are dropped.
    """
    out = {k: v for k, v in schema.items() if k not in ("title", "default", *_CONSTRAINTS)}
    notes = _constraint_notes(schema)
    if notes and "description" in out:
        out["description"] = f"{out['description'].rstrip('.')}. Must be {', '.join(notes)}."
    if "properties" in out:
        out["properties"] = {name: _to_strict(sub) for name, sub in out["properties"].items()}
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    if "anyOf" in out:
        out["anyOf"] = [_to_strict(sub) for sub in out["anyOf"]]
    if isinstance(out.get("items"), dict):
        out["items"] = _to_strict(out["items"])
    return out


def strict_parameters(tool: Tool) -> dict:
    return _to_strict(tool.args_model.model_json_schema())


def tool_specs() -> list[ToolSpec]:
    """Every tool as the model sees it. Each provider adapter wraps these in its own shape."""
    return [
        ToolSpec(
            tool.name,
            tool.description,
            FIND_CUSTOMER_PARAMETERS if tool.name == "find_customer" else strict_parameters(tool),
        )
        for tool in TOOLS
    ]


# --- Execution ---------------------------------------------------------------------

IDEMPOTENCY_TABLE = "idempotency"


def _with_key(conn: sqlite3.Connection, tool: Tool, args: BaseModel, key: str) -> dict:
    """Run a write at most once per key.

    The key row is inserted in the same transaction as the write, so the tool's own commit
    stores both or neither. A second call with the key returns the first result. The table
    is TEMP by default: it is not in sqlite_master, so it is not part of the store's end
    state. With `env.key_schema` naming an attached database file, the keys outlive the
    process; a commit then covers both files at once (SQLite's multi-file commit, which is
    atomic when the store is a file in rollback-journal mode).
    """
    table = f"{env_of(conn).key_schema}.{IDEMPOTENCY_TABLE}"
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} "
                 "(id TEXT PRIMARY KEY, tool TEXT NOT NULL, result TEXT)")
    row = conn.execute(f"SELECT tool, result FROM {table} WHERE id = ?",
                       (key,)).fetchone()
    if row is not None:
        first = json.loads(row["result"]) if row["result"] else {
            "note": "This call was already made; its result was not recorded."}
        return {**first, "replayed": True}
    conn.execute(f"INSERT INTO {table} (id, tool, result) VALUES (?, ?, NULL)",
                 (key, tool.name))
    try:
        result = tool.fn(conn, args)
    except Exception:
        conn.rollback()
        raise
    if "error" in result:   # nothing was written, so the key is released for a corrected call
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (key,))
    else:
        conn.execute(f"UPDATE {table} SET result = ? WHERE id = ?",
                     (json.dumps(result), key))
    conn.commit()
    return result


def execute_tool(conn: sqlite3.Connection, name: str, arguments: str, *,
                 idempotency_key: str | None = None) -> dict:
    """Run one tool call. `arguments` is the JSON string exactly as the model sent it.

    `idempotency_key` applies to write and escalate tools. An injected fault is raised as
    a `ToolFault`: before the tool runs (timeout, unavailable) or after it has committed
    (after_commit).
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        return _error("unknown_tool", f"There is no tool named '{name}'.")
    try:
        args = tool.args_model.model_validate(json.loads(arguments))
    except json.JSONDecodeError as exc:
        return _error("invalid_arguments", f"The arguments are not valid JSON: {exc.msg}.")
    except ValidationError as exc:
        fields = tool.args_model.model_fields
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
            + (f" (expected: {fields[e['loc'][0]].description})"
               if e["loc"] and e["loc"][0] in fields else "")
            for e in exc.errors()
        )
        return _error("invalid_arguments",
                      f"The arguments do not match the schema. {problems}. Nothing was changed.")
    faults = env_of(conn).faults
    fault = faults.next_fault(name) if faults is not None else None
    if fault in ("timeout", "unavailable"):
        raise_fault(fault, name)
    if idempotency_key and tool.kind != "read":
        result = _with_key(conn, tool, args, idempotency_key)
    else:
        result = tool.fn(conn, args)
    if fault == "after_commit":
        raise_fault("timeout", name)
    return result
