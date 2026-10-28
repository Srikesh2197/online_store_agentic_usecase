"""Permission tiers and taint: what the agent may do after it has read untrusted text.

Every tool has a tier (Tool.kind). Text written by someone other than the agent and the
policy, here an order note, is untrusted: it can carry instructions the model may follow
as if they came from the user. A defence that asks the model to ignore them is a request;
this one is structural (Meta's "Rule of Two"): once the run has read untrusted content it
keeps its power to read and to hand off, but loses its power to change the store.

    read       always allowed
    escalate   always allowed: the safe exit
    write      allowed until the run is tainted; then blocked, and the model is told to
               escalate so a person makes the change

The taint is per run and never cleared. Its price is that a legitimate write in a tainted
run also goes to a person.
"""

from arl.env.tools import TOOLS

TIERS = {tool.name: tool.kind for tool in TOOLS}

# Where untrusted text appears: tool -> path to the field in its result.
UNTRUSTED_FIELDS = {"get_order": [("order", "notes")]}


def _get(result: dict, path: tuple[str, ...]):
    for key in path:
        result = result.get(key) if isinstance(result, dict) else None
    return result


class Taint:
    def __init__(self):
        self.tainted = False
        self.sources: list[str] = []

    def observe(self, name: str, result: dict) -> bool:
        """Note a tool result. True if it newly tainted the run."""
        for path in UNTRUSTED_FIELDS.get(name, []):
            if _get(result, path):
                self.sources.append(f"{name}:{'.'.join(path)}")
                if not self.tainted:
                    self.tainted = True
                    return True
        return False

    def check(self, name: str) -> dict | None:
        if TIERS.get(name) == "write" and self.tainted:
            return {"error": "blocked_untrusted_content",
                    "message": "This conversation has read text written by customers or third "
                               "parties (order notes), so changes to the store now need a "
                               "person. Do not retry this action. If the customer's request "
                               "needs it, escalate with escalate_to_human and tell the customer "
                               "a colleague will complete it. Nothing was changed."}
        return None
