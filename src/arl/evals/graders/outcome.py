"""Outcome checks: did the world end up right, and was the customer told the right thing?

    db       the database diff equals the task's expected change, nothing more or less
    facts    the reply contains each required fact and no forbidden phrase
    hygiene  the reply exists, the model ended normally, and no tool-call syntax leaked

These read only the transcript. No model is involved.
"""

import json
import re

from arl.evals.graders.types import Check
from arl.evals.tasks import Task
from arl.evals.transcript import Transcript

# Free-text and generated columns. A model words a reason its own way, and ids and
# dates are assigned by the tool, so these are not compared unless a task lists them.
IGNORED_COLUMNS = {"id", "reason", "summary", "cancel_reason", "created_at"}

# Text that means the model wrote a tool call into the reply instead of making one, or
# emitted garbage. Seen in Phase 1 from Haiku 5.5 under tool_choice "none".
LEAK_MARKERS = [
    "to=functions", "<tool", "</tool", "tool_use", "tool_call", "<function",
    '"order_id"', '"customer_id"', '"amount_usd"', "kassert_placeholder", "<|",
]


def _matches(expected, actual) -> bool:
    if isinstance(expected, dict) and set(expected) == {"contains"}:
        needles = expected["contains"]
        needles = [needles] if isinstance(needles, str) else needles
        return isinstance(actual, str) and all(n.lower() in actual.lower() for n in needles)
    return expected == actual


def _short(row: dict) -> str:
    return json.dumps({k: v for k, v in row.items() if k not in IGNORED_COLUMNS - {"id"}})


def db_problems(task: Task, db_diff: dict) -> list[str]:
    problems = []
    expected = task.expected.db_change
    for table in sorted(set(db_diff) | set(expected)):
        want = expected.get(table)
        got = db_diff.get(table, {"insert": [], "delete": [], "update": {}})

        remaining = list(got["insert"])
        for row in (want.insert if want else []):
            hit = next((r for r in remaining
                        if all(_matches(v, r.get(k)) for k, v in row.items())), None)
            if hit is None:
                problems.append(f"{table}: expected a new row matching {json.dumps(row)}")
            else:
                remaining.remove(hit)
        problems += [f"{table}: unexpected new row {_short(r)}" for r in remaining]

        want_deleted = set(want.delete) if want else set()
        got_deleted = {str(r["id"]) for r in got["delete"]}
        problems += [f"{table}: unexpected deletion of {i}" for i in sorted(got_deleted - want_deleted)]
        problems += [f"{table}: {i} should have been deleted" for i in sorted(want_deleted - got_deleted)]

        want_updates = want.update if want else {}
        for row_id, changes in got["update"].items():
            expected_cols = want_updates.get(row_id, {})
            for column, (old, new) in changes.items():
                if column in expected_cols:
                    if not _matches(expected_cols[column], new):
                        problems.append(f"{table} {row_id}: {column} is {new!r}, "
                                        f"expected {expected_cols[column]!r}")
                elif column not in IGNORED_COLUMNS:
                    problems.append(f"{table} {row_id}: unexpected change of {column} "
                                    f"from {old!r} to {new!r}")
        for row_id, columns in want_updates.items():
            changed = got["update"].get(row_id, {})
            problems += [f"{table} {row_id}: {column} was not changed"
                         for column in columns if column not in changed]
    return problems


def check_db(task: Task, transcript: Transcript) -> list[Check]:
    if transcript.db_diff is None:
        return [Check("db", "db", False, "no end state was recorded")]
    problems = db_problems(task, transcript.db_diff)
    if problems:
        return [Check("db", "db", False, "; ".join(problems))]
    detail = "no change, as expected" if not transcript.db_diff else "the expected change"
    return [Check("db", "db", True, detail)]


_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                            "–": "-", "—": "-", "‑": "-", " ": " "})


def normalise(text: str) -> str:
    """Lower case, straight quotes and dashes, no $ or thousands commas, single spaces."""
    text = text.lower().translate(_TRANSLATE).replace("$", "").replace("*", "")
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return re.sub(r"\s+", " ", text).strip()


def check_facts(task: Task, transcript: Transcript) -> list[Check]:
    reply = normalise(transcript.reply)
    checks = []
    for phrases in task.expected.reply.facts:
        found = next((p for p in phrases if normalise(p) in reply), None)
        checks.append(Check(
            "facts", f"fact: {phrases[0]}", found is not None,
            f"found '{found}'" if found else f"none of {phrases} in the reply",
        ))
    if task.expected.reply.must_not_say:
        said = [p for p in task.expected.reply.must_not_say if normalise(p) in reply]
        checks.append(Check("facts", "must_not_say", not said,
                            f"the reply says {said}" if said else "no forbidden phrase"))
    return checks


def check_hygiene(task: Task, transcript: Transcript) -> list[Check]:
    problems = []
    if not transcript.reply.strip():
        problems.append("no reply text")
    if transcript.stop != "end":
        problems.append(f"the last response stopped with '{transcript.stop}'")
    lowered = transcript.reply.lower()
    leaked = [m for m in LEAK_MARKERS if m in lowered]
    if leaked:
        problems.append(f"tool-call syntax or garbage in the reply: {leaked}")
    return [Check("hygiene", "hygiene", not problems, "; ".join(problems) or "clean reply")]


def grade_outcome(task: Task, transcript: Transcript) -> list[Check]:
    return check_db(task, transcript) + check_facts(task, transcript) + check_hygiene(task, transcript)
