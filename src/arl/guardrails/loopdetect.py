"""Loop detection: the same tool called with the same arguments, again and again.

A read gives the same answer the third time it is asked. Repeating it is a loop, whether
the model is polling ("keep checking until delivered") or following notes in a circle. The
detector works in two stages:

    3rd identical call   not run; the model gets a `repeated_call` error saying why
    4th and later        not run, and the loop stops: one reply-only call, status loop_detected

Novel-but-endless work (a new order id every turn) is not a repeat. The token, dollar and
step limits catch that.
"""

import json
from collections import Counter

BLOCK_AT = 3
STOP_AT = 4


def call_key(name: str, arguments: str) -> str:
    try:
        canonical = json.dumps(json.loads(arguments), sort_keys=True)
    except json.JSONDecodeError:
        canonical = arguments
    return f"{name}:{canonical}"


class LoopDetector:
    def __init__(self, block_at: int = BLOCK_AT, stop_at: int = STOP_AT):
        self.block_at, self.stop_at = block_at, stop_at
        self.counts: Counter[str] = Counter()
        self.stop = False

    def check(self, name: str, arguments: str) -> dict | None:
        """Count this call. An error result if it must not run, else None."""
        key = call_key(name, arguments)
        self.counts[key] += 1
        n = self.counts[key]
        if n >= self.stop_at:
            self.stop = True
        if n >= self.block_at:
            return {"error": "repeated_call",
                    "message": f"You have already called {name} with these arguments {n - 1} "
                               "times and the result will not change. Do not call it again; "
                               "reply to the customer with what you know, or escalate."}
        return None
