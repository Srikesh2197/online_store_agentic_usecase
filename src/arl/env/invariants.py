"""Policy invariants, enforced inside the write tools (Stage 5).

Until Stage 5 the policy lived only in the prompt: c13 passed because the model chose not
to cancel a shipped order, not because it could not. These checks are the part of the
policy that is exact enough to hold in code, for every caller of the tool, whatever the
model was told or tricked into:

    refund    the order's refunds in total never exceed what was paid for it
    owner     a write touches only an order of the signed-in sender (when there is one)
    status    cancel and address change only while the order is `processing`

They are off unless the trial's `env.invariants` is on, so the off arm sees the tools as
they were. The judgement calls of the policy (is it defective, is it within 30 days, which
items are affected) stay in the prompt.
"""

import sqlite3

from arl.env.store import dollars, env_of

NOTHING_CHANGED = "Nothing was changed."


def _violation(message: str) -> dict:
    return {"error": "policy_violation", "message": f"{message} {NOTHING_CHANGED}"}


def check(conn: sqlite3.Connection, tool: str, order, *, cents: int = 0) -> dict | None:
    """An error result if `tool` on `order` would break an invariant, else None."""
    env = env_of(conn)
    if not env.invariants:
        return None
    if env.sender_customer_id and order["customer_id"] != env.sender_customer_id:
        return _violation(f"Order {order['id']} does not belong to the signed-in customer, so "
                          "it cannot be changed from this ticket.")
    if tool in ("cancel_order", "update_shipping_address") and order["status"] != "processing":
        action = "cancelled" if tool == "cancel_order" else "re-addressed"
        return _violation(f"Order {order['id']} is '{order['status']}'; only a processing order "
                          f"can be {action}.")
    if tool == "issue_refund":
        refunded = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?", (order["id"],)
        ).fetchone()[0]
        if refunded + cents > order["total_cents"]:
            return _violation(
                f"Order {order['id']} was paid {dollars(order['total_cents'])} and "
                f"{dollars(refunded)} is already refunded, so at most "
                f"{dollars(order['total_cents'] - refunded)} more can be refunded; "
                f"got {dollars(cents)}.")
    return None
