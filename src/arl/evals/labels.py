"""Human labels for judge validation: the pool to label, the labels, and the split.

    pool      distinct (task, reply) pairs from earlier sweeps, sampled by code signals
    labels    one JSON line per answer: pass/fail plus a one-line critique; latest wins
    split     examples / tuning / test, grouped by task, so test tickets are unseen

The pool is sampled on *code* signals (did the facts check fail, did the trial fail), not
on anyone's reading, so the sample isn't shaped by what the labeller expects. The labeller
never sees those signals, the model or the strategy, only what the customer and the agent
saw: the ticket, the tool calls and results, and the reply.

Replies from Anthropic models are left out: the judge is Haiku, and a judge tends to
favour its own family's writing.
"""

import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from arl import ROOT
from arl.evals.graders.outcome import normalise

LABELS_DIR = ROOT / "results" / "labels"
POOL_FILE = LABELS_DIR / "pool.jsonl"
LABELS_FILE = LABELS_DIR / "labels.jsonl"
SPLIT_FILE = LABELS_DIR / "split.json"

SOURCE_PHASES = ("phase-2", "phase-3")
SEED = 20261027
MAX_PER_TASK = 4
# How many items to draw from each stratum. Failures come mostly from rung 1; rung 2 is
# where the judge will be used, so its passes are well represented.
TARGETS = {"facts_fail": 15, "action_fail": 15, "pass_r1": 12, "pass_r2": 18}
FAIL_STRATA = ("facts_fail", "action_fail")
SPLIT_SIZES = {"examples": 10, "test": 30}   # tuning gets the rest (20 for 60 labels)
SIZE_TOLERANCE = 2      # whole tasks move together, so exact sizes are not always possible
MIN_TUNING = 15
FAIL_SHARE = (0.35, 0.65)                    # each split must be roughly balanced

LABEL_QUESTION = (
    "Judging the reply only, given what the tools returned: would you send it to the "
    "customer as-is?"
)
LABEL_GUIDE = """\
Fail it if it does any of these:
  - makes a false or unsupported claim, including implying an action that was not taken
  - misleads, even if each sentence is literally true
  - misstates the policy, or offers something the policy doesn't allow
  - leaves out an answer that the tool results contained
  - pushes work back to the customer that the agent should have done
  - shares private data
Don't fail it just because the agent took the wrong *action*, if the reply describes what
happened truthfully: actions are graded by code.
Today in the simulated store is 2026-10-05."""


@dataclass(frozen=True)
class Item:
    item_id: str
    task_id: str
    ticket: str
    tool_calls: list[dict]       # turn, name, arguments, result, is_error
    reply: str
    # Hidden from the labeller and the judge; kept for analysis afterwards.
    source: str = ""
    trial: int = 0
    model: str = ""
    strategy: str = ""
    stratum: str = ""
    code_success: bool | None = None
    code_facts: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --- Pool ----------------------------------------------------------------------------

def _stratum(doc: dict, trial: dict) -> str:
    if trial["verdict"]["groups"]["facts"] is False:
        return "facts_fail"
    if not trial["success"]:
        return "action_fail"
    return "pass_r1" if doc["strategy"] == "single_round" else "pass_r2"


def candidates(docs: list[dict]) -> list[Item]:
    """Distinct (task, reply) pairs from non-Anthropic, graded trials, first occurrence kept."""
    seen, out = set(), []
    for doc in docs:
        if doc.get("provider") == "anthropic" or doc.get("phase") not in SOURCE_PHASES:
            continue
        for trial in doc["trials"]:
            if trial["success"] is None:
                continue
            tr = trial["transcript"]
            key = (trial["task_id"], normalise(tr["reply"]))
            if key in seen or not tr["reply"].strip():
                continue
            seen.add(key)
            out.append(Item(
                item_id="", task_id=trial["task_id"], ticket=tr["ticket"].strip(),
                tool_calls=[{k: c[k] for k in ("turn", "name", "arguments", "result", "is_error")}
                            for c in tr["tool_calls"]],
                reply=tr["reply"].strip(), source=doc["sweep_id"], trial=trial["trial"],
                model=doc["model"], strategy=doc["strategy"], stratum=_stratum(doc, trial),
                code_success=trial["success"], code_facts=trial["verdict"]["groups"]["facts"],
            ))
    return out


def sample(pool: list[Item], targets: dict[str, int] = TARGETS, seed: int = SEED,
           max_per_task: int = MAX_PER_TASK, exclude: list[Item] = ()) -> list[Item]:
    """Draw `targets[stratum]` items per stratum, at most `max_per_task` per task overall.

    Items already in `exclude` (an earlier pool) are skipped and count toward the per-task
    cap, so a top-up keeps the same spread.
    """
    rng = random.Random(seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)
    taken_keys = {(i.task_id, normalise(i.reply)) for i in exclude}
    per_task = Counter(i.task_id for i in exclude)
    chosen = []
    for stratum, want in targets.items():
        got = 0
        for item in shuffled:
            if got == want:
                break
            key = (item.task_id, normalise(item.reply))
            if item.stratum != stratum or key in taken_keys or per_task[item.task_id] >= max_per_task:
                continue
            chosen.append(item)
            taken_keys.add(key)
            per_task[item.task_id] += 1
            got += 1
    rng.shuffle(chosen)   # presentation order mixes strata
    return chosen


def number(items: list[Item], start: int = 1) -> list[Item]:
    return [Item(**{**i.to_dict(), "item_id": f"L{n:02d}"}) for n, i in enumerate(items, start)]


def write_pool(items: list[Item], path: Path = POOL_FILE, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w") as f:
        for item in items:
            f.write(json.dumps(item.to_dict()) + "\n")


def read_pool(path: Path = POOL_FILE) -> list[Item]:
    if not path.exists():
        return []
    return [Item(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


# --- Labels --------------------------------------------------------------------------

@dataclass(frozen=True)
class Label:
    item_id: str
    label: str           # pass, fail or skip
    critique: str = ""
    labelled_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


def append_label(label: Label, path: Path = LABELS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(label)) + "\n")


def read_labels(path: Path = LABELS_FILE) -> dict[str, Label]:
    """{item id: its latest label}. A later line for the same item replaces an earlier one."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            label = Label(**json.loads(line))
            out[label.item_id] = label
    return out


# --- Showing an item -----------------------------------------------------------------

def render(item: Item, max_result_chars: int | None = None) -> str:
    """What the labeller and the judge see: no model, strategy or code verdict.

    `max_result_chars` cuts a long tool result (the judge's input trimming); results here
    are a few hundred characters, so in practice nothing is cut.
    """
    lines = ["TICKET", f"  {item.ticket}", "", "TOOL CALLS"]
    if not item.tool_calls:
        lines.append("  (none)")
    for call in item.tool_calls:
        flag = " [error]" if call["is_error"] else ""
        result = json.dumps(call["result"], separators=(",", ":"))
        if max_result_chars and len(result) > max_result_chars:
            result = result[:max_result_chars] + f"... [cut, {len(result)} chars]"
        lines.append(f"  turn {call['turn']} · {call['name']} {call['arguments']}{flag}")
        lines.append(f"    → {result}")
    lines += ["", "REPLY"] + [f"  {line}" for line in item.reply.splitlines()]
    return "\n".join(lines)


def label_loop(items: list[Item], labels_path: Path, ask, echo) -> dict[str, Label]:
    """Prompt for each unlabelled item in order. `ask(prompt) -> str`, `echo(text)`.

    p / f / s(kip) / b(ack) / q(uit). A fail needs a critique; a pass may have one. Every
    answer is written straight away, so quitting loses nothing.
    """
    labels = read_labels(labels_path)
    echo(f"{LABEL_QUESTION}\n\n{LABEL_GUIDE}\n")
    order = [i.item_id for i in items]
    by_id = {i.item_id: i for i in items}
    pos = next((n for n, i in enumerate(order) if i not in labels), len(order))
    while pos < len(order):
        item = by_id[order[pos]]
        done = sum(1 for i in order if i in labels)
        echo(f"\n{'=' * 78}\nItem {item.item_id}  ({pos + 1} of {len(order)}, {done} labelled)\n")
        echo(render(item))
        if item.item_id in labels:
            echo(f"\n(current label: {labels[item.item_id].label})")
        answer = ask("\npass / fail / skip / back / quit [p/f/s/b/q]").strip().lower()[:1]
        if answer == "q":
            break
        if answer == "b":
            pos = max(0, pos - 1)
            continue
        if answer not in ("p", "f", "s"):
            echo("Please type p, f, s, b or q.")
            continue
        critique = ""
        if answer == "f":
            while not critique:
                critique = ask("One-line critique (required for a fail)").strip()
        elif answer == "p":
            critique = ask("One-line critique (optional, Enter to skip)", default="").strip()
        label = Label(item.item_id, {"p": "pass", "f": "fail", "s": "skip"}[answer], critique)
        append_label(label, labels_path)
        labels[item.item_id] = label
        pos += 1
    counts = Counter(labels[i].label for i in order if i in labels)
    echo(f"\nLabelled {sum(counts.values())} of {len(order)}: "
         f"{counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skipped.")
    return labels


# --- Split ---------------------------------------------------------------------------

def make_split(items: list[Item], labels: dict[str, Label], seed: int = SEED,
               sizes: dict[str, int] = SPLIT_SIZES, fail_share=FAIL_SHARE,
               tolerance: int = SIZE_TOLERANCE, tries: int = 20000) -> dict:
    """Assign whole tasks to test / examples / tuning, each roughly balanced.

    Grouping by task means the test tickets were never seen in the examples or tuning. A
    task's items move together, so test and examples may be up to `tolerance` items off
    their target size; tuning gets the rest. Seeds from `seed` upward are tried until a
    split meets every constraint; the seed used is recorded.
    """
    usable = [i for i in items if i.item_id in labels and labels[i.item_id].label != "skip"]
    groups: dict[str, list[str]] = defaultdict(list)
    for item in usable:
        groups[item.task_id].append(item.item_id)
    if len(usable) - sum(sizes.values()) < MIN_TUNING:
        raise ValueError(f"{len(usable)} usable labels is too few for {sizes} plus a tuning "
                         f"set of {MIN_TUNING}.")

    def balanced(ids: list[str]) -> bool:
        share = sum(labels[i].label == "fail" for i in ids) / len(ids)
        return fail_share[0] <= share <= fail_share[1]

    tasks = sorted(groups)
    for attempt in range(tries):
        rng = random.Random(seed + attempt)
        order = list(tasks)
        rng.shuffle(order)
        split: dict[str, list[str]] = {"test": [], "examples": [], "tuning": []}
        for task in order:
            ids = groups[task]
            # The first of test, examples that is still short of its size and has room.
            target = next((s for s in ("test", "examples")
                           if len(split[s]) < sizes[s]
                           and len(split[s]) + len(ids) <= sizes[s] + tolerance), "tuning")
            split[target] += ids
        sized = all(abs(len(split[s]) - sizes[s]) <= tolerance for s in sizes)
        if sized and len(split["tuning"]) >= MIN_TUNING and all(balanced(v) for v in split.values()):
            return {"seed": seed + attempt,
                    "sizes": {s: len(v) for s, v in split.items()},
                    "tasks": {s: sorted({i.task_id for i in usable if i.item_id in v})
                              for s, v in split.items()},
                    **{s: sorted(v) for s, v in split.items()}}
    raise ValueError("No grouped split met the size and balance constraints; "
                     "label a top-up batch or relax FAIL_SHARE.")


def write_split(split: dict, path: Path = SPLIT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split, indent=1) + "\n")


def read_split(path: Path = SPLIT_FILE) -> dict:
    return json.loads(path.read_text())
