"""Live crash demo (Stage 7): run a task as a thread with the real model, and kill the process
right after its first committed write. Then resume it with `arl resume <thread>`.

    agentic/bin/python scripts/crash_demo.py c09 demo-crash-c09
    agentic/bin/arl resume demo-crash-c09
    agentic/bin/arl audit demo-crash-c09

The kill is `os._exit` straight after the write tool returns: the step's checkpoint is not
written, so the resumed run re-runs the whole `tools` step, and the idempotency key in the
thread's keys.db must stop the write from happening twice. Costs one ordinary run.
"""

import os
import sys

from dotenv import load_dotenv

from arl import ROOT
from arl.env.tools import _BY_NAME
from arl.evals.tasks import by_id, load_tasks
from arl.evals.trial_env import trial_store
from arl.framework import graph_agent, threads
from arl.framework.models import make_chat_model
from arl.llm.pricing import load_models


def main(task_id: str, thread_id: str) -> None:
    load_dotenv(ROOT / ".env")
    tasks = by_id(load_tasks("capability")) | by_id(load_tasks("adversarial"))
    task = next(t for t in tasks.values() if t.id.startswith(task_id + "-"))
    real = graph_agent.execute_tool

    def execute_then_die(conn, name, arguments, **kwargs):
        result = real(conn, name, arguments, **kwargs)
        if _BY_NAME[name].kind == "write" and "error" not in result:
            print(f"KILLED right after {name} committed: {result}", flush=True)
            os._exit(137)
        return result

    graph_agent.execute_tool = execute_then_die
    threads.start_thread(task.ticket.strip(), ticket_id=task.id,
                         source_store=trial_store(task, invariants=True),
                         chat=make_chat_model(load_models()["default"]), strategy="graph_all",
                         thread_id=thread_id, task_id=task.id)
    print("The run ended without a write; nothing was killed.")


if __name__ == "__main__":
    main(*sys.argv[1:])
