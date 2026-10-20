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
from pydantic import BaseModel, ConfigDict

from arl.env.tools import TOOLS

TASKS_DIR = Path(__file__).parent / "tasks"
DEFAULT_SET = "capability"

TOOL_NAMES = {tool.name for tool in TOOLS}
KINDS = {tool.kind for tool in TOOLS}

Category = Literal["read", "write", "refuse", "escalate"]
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


def expand_tools(names: list[str]) -> set[str]:
    """Tool names, with "@kind" standing for every tool of that kind."""
    out = set()
    for name in names:
        out |= ({t.name for t in TOOLS if t.kind == name[1:]} if name.startswith("@")
                else {name})
    return out


def consistency_problems(task: Task) -> list[str]:
    """Ways a task contradicts itself or the store. An empty list means it is usable."""
    from arl.env.seed import new_store
    from arl.evals.dbdiff import snapshot

    problems = []
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
    problems += [f"unknown tool '{n}'" for n in names if n not in TOOL_NAMES]
    problems += [f"unknown tool kind '{n}'" for n in task.trajectory.must_not_call
                 if n.startswith("@") and n[1:] not in KINDS]

    store = snapshot(new_store())
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

