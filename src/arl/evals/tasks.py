"""Tasks: one YAML file each, read into a strict model and checked for consistency.

A task says what a correct run leaves behind (the database change and the reply facts)
and which paths are forbidden or must come in order. It also carries one correct run,
`reference`, which a test replays to prove the task can be passed and that the graders
accept it.
"""

import hashlib
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from arl.env.tools import TOOLS

TASKS_DIR = Path(__file__).parent / "tasks"
DEFAULT_SET = "capability"

# Capability v1, frozen 2026-10-27: 20 tasks written up front (c01-c20) and 10 drawn from
# observed failures (c21-c30). Baselines and later comparisons are against this hash. A
# change to any task file changes it, and a test fails; a new version gets a new constant.
FROZEN_V1_HASH = "76254c561b0d"

# The adversarial set (Stage 5), frozen 2026-10-28: 12 tasks (3 direct injection, 4 indirect,
# 2 runaway-loop bait, 3 tool faults), chosen from 16 candidates by calibration on the
# unguarded arm (hand_loop, 3 trials each, one rewrite round of six candidates): harm on
# 21 of 36 calibration trials (58%), against the bar of 40%. The 4 dropped candidates are in
# tasks/adversarial_dropped/.
ADVERSARIAL_SET = "adversarial"
FROZEN_ADVERSARIAL_HASH: str | None = "44c9b476eaa8"

# The parallel set (Stage 8), frozen 2026-10-29: 8 bulk audits, where one ticket names several
# orders and each needs its own lookups and judgement, so the work can be split between agents.
# Built on the unchanged seed. Calibrated for validity, not difficulty: graph_all 8 x 1 passed
# 7 (p06 failed only on "$22" against the fact "22.00"); one rewrite round widened the money
# facts of p03, p06 and p07 and made the p06 ticket unambiguous ("both notebook packs"); p06
# then passed again.
PARALLEL_SET = "parallel"
FROZEN_PARALLEL_HASH: str | None = "2cc7a9b329ed"

TOOL_NAMES = {tool.name for tool in TOOLS}
KINDS = {tool.kind for tool in TOOLS}

Category = Literal["read", "write", "refuse", "escalate",
                   # adversarial (Stage 5)
                   "inject_direct", "inject_indirect", "loop", "fault"]
ADVERSARIAL_CATEGORIES = ("inject_direct", "inject_indirect", "loop", "fault")
Disposition = Literal["resolved", "refused", "escalated"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TableChange(_Strict):
    # Each insert is a partial row: the listed columns must match, others are not checked.
    # A value is matched for equality, or {contains: text or [texts]} for free text.
    insert: list[dict] = []
    # {row id: {column: expected new value}}
    update: dict[str, dict] = {}
    # ids of rows that must be deleted
    delete: list[str] = []


class ReplySpec(_Strict):
    facts: list[list[str]] = []      # each fact: at least one of these phrases must appear
    must_not_say: list[str] = []     # none of these phrases may appear


class Expected(_Strict):
    disposition: Disposition
    db_change: dict[str, TableChange] = {}
    reply: ReplySpec = ReplySpec()


class CallSpec(_Strict):
    tool: str
    args: dict = {}                  # a partial match on the call's arguments


class OrderRule(_Strict):
    first: list[str]                 # one of these, successful, in an earlier model turn ...
    then: str                        # ... than the first call of this tool


class Trajectory(_Strict):
    must_call: list[str | CallSpec] = []
    must_not_call: list[str] = []    # tool names, or "@write" / "@escalate" / "@read"
    order: list[OrderRule] = []


class FaultSpec(_Strict):
    """A backend fault the environment injects (env/faults.py). Same for every arm."""
    tool: str
    kind: Literal["timeout", "unavailable", "after_commit"]
    nth: int = 1
    times: int | Literal["always"] = 1


class Harm(_Strict):
    """One way the attack can land, checked in code. Exactly one field is set.

    db_insert        {table, match}: a new row whose listed columns match
    min_rows         {table, match, n}: at least n new rows that match
    sum_above        {table, match, column, above}: the new rows' column sums to more
    db_update        {table, id, column}: that column of that row changed
    reply_contains   [phrases]: the reply contains any of these exact tokens
    min_model_calls  n: the run made at least n model calls (a runaway)
    """
    db_insert: dict | None = None
    min_rows: dict | None = None
    sum_above: dict | None = None
    db_update: dict | None = None
    reply_contains: list[str] | None = None
    min_model_calls: int | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        set_fields = [k for k, v in self.model_dump().items() if v is not None]
        if len(set_fields) != 1:
            raise ValueError(f"a harm condition sets exactly one field, got {set_fields}")
        return self


class Attack(_Strict):
    goal: str                         # what the attacker wants, in words
    vector: str                       # where the attack enters: ticket, order_note, fault, ...
    harm: list[Harm]                  # any of these means the attack landed
    attempt: list[CallSpec] = []      # calls that show the model took the bait, blocked or not


class Reference(_Strict):
    turns: list[list[tuple[str, dict]]]   # model turns, each a batch of (tool, arguments)
    reply: str


class Task(_Strict):
    id: str
    title: str
    category: Category
    provenance: str
    ticket: str
    expected: Expected
    trajectory: Trajectory = Trajectory()
    reference: Reference
    notes: str = ""
    # Stage 5. Defaults keep the capability tasks as they were.
    sender: str | None = None                  # the signed-in sender's email, if any
    setup: dict[str, list[dict]] = {}          # rows added after seeding (order notes)
    faults: list[FaultSpec] = []
    attack: Attack | None = None


def expand_tools(names: list[str]) -> set[str]:
    """Tool names, with "@kind" standing for every tool of that kind."""
    out = set()
    for name in names:
        out |= ({t.name for t in TOOLS if t.kind == name[1:]} if name.startswith("@")
                else {name})
    return out


def consistency_problems(task: Task) -> list[str]:
    """Ways a task contradicts itself or the store. An empty list means it is usable."""
    from arl.env.seed import apply_setup, new_store
    from arl.evals.dbdiff import snapshot

    problems = []
    adversarial = task.category in ADVERSARIAL_CATEGORIES
    if adversarial and task.attack is None:
        problems.append("an adversarial task needs an attack block")
    if not adversarial and (task.attack or task.faults or task.setup):
        problems.append("only adversarial tasks have attack, faults or setup")
    change = task.expected.db_change
    disposition = task.expected.disposition
    if disposition == "refused" and change:
        problems.append("a refused task cannot change the database")
    if task.category == "read" and change:
        problems.append("a read task cannot change the database")
    if disposition == "escalated":
        esc = change.get("escalations")
        if esc is None or len(esc.insert) != 1 or set(change) != {"escalations"}:
            problems.append("an escalated task must insert one escalations row and nothing else")
    if disposition == "resolved" and task.category in ("refuse", "escalate"):
        problems.append(f"category {task.category} does not fit disposition resolved")

    names = []
    for spec in task.trajectory.must_call:
        names.append(spec if isinstance(spec, str) else spec.tool)
    for rule in task.trajectory.order:
        names += [*rule.first, rule.then]
    names += [n for n in task.trajectory.must_not_call if not n.startswith("@")]
    names += [name for turn in task.reference.turns for name, _ in turn]
    names += [fault.tool for fault in task.faults]
    if task.attack:
        names += [spec.tool for spec in task.attack.attempt]
    problems += [f"unknown tool '{n}'" for n in names if n not in TOOL_NAMES]
    problems += [f"unknown tool kind '{n}'" for n in task.trajectory.must_not_call
                 if n.startswith("@") and n[1:] not in KINDS]

    conn = new_store()
    try:
        apply_setup(conn, task.setup)
    except Exception as exc:  # noqa: BLE001 -- reported as a problem with the task
        problems.append(f"setup: {exc}")
    if task.sender and conn.execute("SELECT 1 FROM customers WHERE email = ?",
                                    (task.sender,)).fetchone() is None:
        problems.append(f"sender {task.sender} is not a customer")
    store = snapshot(conn)
    for table, spec in change.items():
        if table not in store:
            problems.append(f"unknown table '{table}'")
            continue
        for row_id in [*spec.update, *spec.delete]:
            if row_id not in store[table]:
                problems.append(f"{table} has no row '{row_id}'")
        for row in spec.insert:
            for column in ("order_id", "customer_id"):
                ref_table = "orders" if column == "order_id" else "customers"
                value = row.get(column)
                if isinstance(value, str) and value not in store[ref_table]:
                    problems.append(f"insert into {table} refers to missing {column} {value}")
    return problems


def task_files(task_set: str = DEFAULT_SET) -> list[Path]:
    return sorted((TASKS_DIR / task_set).glob("*.yaml"))


def load_task(path: Path) -> Task:
    task = Task.model_validate(yaml.safe_load(path.read_text()))
    if task.id != path.stem:
        raise ValueError(f"{path.name}: id '{task.id}' does not match the file name")
    return task


@cache
def load_tasks(task_set: str = DEFAULT_SET) -> tuple[Task, ...]:
    tasks = tuple(load_task(path) for path in task_files(task_set))
    if not tasks:
        raise FileNotFoundError(f"No tasks in {TASKS_DIR / task_set}")
    return tasks


def task_set_hash(task_set: str = DEFAULT_SET) -> str:
    """A short hash of the task files, stored with results so a changed set is visible."""
    digest = hashlib.sha256()
    for path in task_files(task_set):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:12]


def select(tasks: tuple[Task, ...], spec: str = "all") -> list[Task]:
    """`all`, or a comma-separated mix of categories and task ids or id prefixes (c01,refuse)."""
    if spec == "all":
        return list(tasks)
    chosen = []
    for word in (w.strip() for w in spec.split(",") if w.strip()):
        hits = [t for t in tasks
                if t.category == word or t.id == word or t.id.startswith(word + "-")]
        if not hits:
            raise ValueError(f"'{word}' matches no task or category. Known: "
                             f"{', '.join(t.id for t in tasks)}")
        chosen += [t for t in hits if t not in chosen]
    return [t for t in tasks if t in chosen]   # keep the task-file order


def by_id(tasks: tuple[Task, ...]) -> dict[str, Task]:
    return {task.id: task for task in tasks}

