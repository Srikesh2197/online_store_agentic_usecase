"""A child process for tests/test_crash_recovery.py: start a thread, then die mid-run.

    python tests/crash_child.py <root> <thread_id> <where> <keys> [invariants]

where   after_write   die right after issue_refund returns (committed, key result stored)
        inside_tool   die inside issue_refund, after its commit, before the key's result is
                      stored
        in_model      die inside the second model call, before any write
keys    file          the thread's keys in the attached keys.db (the Stage 7 setting)
        temp          the keys in a TEMP table, as in the eval arms: they die with the process
invariants  on (default) or off: whether the write tools enforce the amount cap

`os._exit` ends the process at once, like SIGKILL: no `finally`, no checkpoint for the step
that was running, no flush.
"""

import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from arl.env import tools
from arl.env.seed import new_store
from arl.env.store import EnvConfig
from arl.framework import graph_agent, threads
from arl.framework.models import ChatSetup
from fake_chat import FakeToolChatModel
from scripted import calls, reply

TICKET = "The blender in order ORD-1002 arrived with a cracked jug. Please refund it."
LOOK = ("get_order", {"order_id": "ORD-1002"})
REFUND = ("issue_refund", {"order_id": "ORD-1002", "amount_usd": "79.99",
                           "reason": "Jug arrived cracked"})
STEPS = [calls(LOOK), calls(REFUND), reply("I've refunded $79.99.")]
KILLED = 137


class DyingChat(FakeToolChatModel):
    die_on_call: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if len(self.calls) + 1 == self.die_on_call:
            os._exit(KILLED)
        return super()._generate(messages, stop, run_manager, **kwargs)


def main(root: str, thread_id: str, where: str, keys: str, invariants: str = "on") -> None:
    if where == "after_write":
        real = graph_agent.execute_tool

        def execute_then_die(conn, name, arguments, **kwargs):
            result = real(conn, name, arguments, **kwargs)
            if name == "issue_refund" and "error" not in result:
                os._exit(KILLED)
            return result

        graph_agent.execute_tool = execute_then_die
    elif where == "inside_tool":
        tool = tools._BY_NAME["issue_refund"]

        def refund_then_die(conn, args):
            tool.fn(conn, args)   # commits the refund and the key row (result not yet stored)
            os._exit(KILLED)

        tools._BY_NAME["issue_refund"] = replace(tool, fn=refund_then_die)
    if keys == "temp":
        create = threads.create_store

        def temp_keys(folder, source):
            conn = create(folder, source)
            conn.env = replace(conn.env, key_schema="temp")
            return conn

        threads.create_store = temp_keys
    chat = DyingChat(steps=STEPS, die_on_call=2 if where == "in_model" else 0)
    source = new_store()
    source.env = EnvConfig(invariants=invariants == "on")
    threads.start_thread(TICKET, ticket_id="crash", source_store=source,
                         chat=ChatSetup(chat, "openai", "gpt-6-luna"), strategy="graph_all",
                         thread_id=thread_id, root=Path(root), sleep=lambda s: None)
    sys.exit(0)   # not reached when the process is killed


if __name__ == "__main__":
    main(*sys.argv[1:])
