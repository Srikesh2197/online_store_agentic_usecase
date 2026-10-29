"""Scripted multi-agent runs: one script per agent, whatever order the threads run in.

Specialists asked in one turn run in threads, so a single shared script would be consumed
in an order that depends on timing. `AgentRouter` is a `send` for tests/wire.py that reads
the agent's name from the fixed role line in the request's system prompt
(`## Your role: orders`) and answers from that agent's own `ScriptedModel`. Each script's
call ids carry the agent's name, so ids differ across agents as real ones do.

    router = AgentRouter("openai", supervisor=[...], orders=[...])
    setup = wire_setup(router, "openai")
"""

import json
import re
import threading

from scripted import ScriptedModel

ROLE = re.compile(r"## Your role: (\w+)")


class AgentRouter:
    def __init__(self, provider: str, *, on_request=None, **scripts):
        self.provider = provider
        self.models = {name: ScriptedModel(provider, *steps, prefix=f"{name}_")
                       for name, steps in scripts.items()}
        self.log: list[tuple[str, dict]] = []    # (agent, request body), in arrival order
        self.on_request = on_request              # called with (agent, body) before answering
        self._lock = threading.Lock()

    @staticmethod
    def agent_of(body: dict) -> str:
        found = ROLE.search(json.dumps(body))
        return found.group(1) if found else "main"

    def requests_of(self, agent: str) -> list[dict]:
        return list(self.models[agent].requests)

    def __call__(self, body: dict):
        agent = self.agent_of(body)
        with self._lock:
            self.log.append((agent, body))
        if self.on_request:
            self.on_request(agent, body)
        if agent not in self.models:
            raise AssertionError(f"No script for agent '{agent}'.")
        with self._lock:
            return self.models[agent](body)

    @property
    def requests(self) -> list[dict]:   # what wire.py reads to number its responses
        return [body for _, body in self.log]
