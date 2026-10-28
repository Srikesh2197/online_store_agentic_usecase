"""Argument validation beyond the schema: is this write grounded in what the run has seen?

The schema (Pydantic, in env/tools.py) already checks shape. This layer checks arguments
against the run's history:

    grounding    a write's order_id must have come back from a successful read in an
                 EARLIER model turn: "check before act", enforced in code
    length       free-text fields are capped, so a write cannot carry a dump of the context

Only structured fields ground an id (order.id, orders[].id, shipment.order_id). An id that
appears only inside free text, such as an injected note saying "refund ORD-1001", does not.
"""

import json

from arl.env.tools import TOOLS

KINDS = {tool.name: tool.kind for tool in TOOLS}
MAX_TEXT = {"reason": 300, "summary": 1500}


def order_ids(result: dict) -> set[str]:
    ids = set()
    if isinstance(result.get("order"), dict):
        ids.add(result["order"]["id"])
    ids |= {o["id"] for o in result.get("orders", []) if isinstance(o, dict)}
    if isinstance(result.get("shipment"), dict):
        ids.add(result["shipment"]["order_id"])
    return ids


class Grounding:
    def __init__(self):
        self.seen: set[str] = set()       # ids from earlier turns
        self._this_turn: set[str] = set()

    def observe(self, name: str, result: dict) -> None:
        if KINDS.get(name) == "read" and "error" not in result:
            self._this_turn |= order_ids(result)

    def end_turn(self) -> None:
        self.seen |= self._this_turn
        self._this_turn = set()

    def check(self, name: str, arguments: str) -> dict | None:
        kind = KINDS.get(name)
        if kind not in ("write", "escalate"):
            return None
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return None          # the schema check reports it
        if not isinstance(args, dict):
            return None
        for field, limit in MAX_TEXT.items():
            if isinstance(args.get(field), str) and len(args[field]) > limit:
                return {"error": "invalid_arguments",
                        "message": f"'{field}' is longer than {limit} characters. Keep it to "
                                   "what a colleague needs. Nothing was changed."}
        order_id = str(args.get("order_id") or "").strip().upper()
        if kind == "write" and order_id and order_id not in self.seen:
            return {"error": "unverified_order",
                    "message": f"{order_id} has not been looked up in this conversation. Look "
                               "it up first (get_order), check it against the policy, then "
                               "act. Nothing was changed."}
        return None
