"""The store a trial runs against: seeded, plus the task's setup, with its environment set.

The environment belongs to the task (its order notes, its faults, its signed-in sender) and
to the arm (whether the write tools enforce the invariants). Every arm of an experiment
gets the same task environment.
"""

import sqlite3

from arl.env.faults import FaultInjector
from arl.env.seed import apply_setup, new_store
from arl.env.store import EnvConfig
from arl.evals.tasks import Task


def sender_customer_id(conn: sqlite3.Connection, email: str | None) -> str | None:
    if not email:
        return None
    row = conn.execute("SELECT id FROM customers WHERE email = ?", (email.lower(),)).fetchone()
    return row["id"] if row else None


def trial_store(task: Task, *, invariants: bool = False, faults: bool = True) -> sqlite3.Connection:
    conn = new_store()
    apply_setup(conn, task.setup)
    injector = (FaultInjector.from_specs([f.model_dump() for f in task.faults])
                if faults and task.faults else None)
    conn.env = EnvConfig(invariants=invariants,
                         sender_customer_id=sender_customer_id(conn, task.sender),
                         faults=injector)
    return conn
