"""Tables from results files: per-arm summary, categories, per-task variance, paired.

An arm is one results file: one model, one strategy, k trials per task. Rates leave out
error trials (API failures), which are counted separately.

pass^k per task with c successes in n trials is C(c, k) / C(n, k): the chance that k
trials drawn from those n all succeed. pass^1 is the success rate; pass^n is 1 only for a
task that never failed.
"""

import json
import statistics
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

from arl.evals.graders import GROUPS, Verdict, grade
from arl.evals.tasks import by_id, load_tasks, task_set_hash
from arl.evals.transcript import Transcript

CATEGORIES = ("read", "write", "refuse", "escalate")
SIGNIFICANCE = 0.05


# --- Loading -------------------------------------------------------------------------

def load_results(path: Path, regrade: bool = False) -> dict:
    """A results file. With `regrade`, every stored transcript is graded again against the
    task files as they are now, so a fixed phrase list or rule shows up without a re-run."""
    doc = json.loads(Path(path).read_text())
    if regrade:
        tasks = by_id(load_tasks(doc["task_set"]))
        for trial in doc["trials"]:
            verdict = grade(tasks[trial["task_id"]], Transcript.from_dict(trial["transcript"]))
            trial["verdict"], trial["success"] = verdict.to_dict(), verdict.success
        doc["regraded_with"] = task_set_hash(doc["task_set"])
    return doc


def _matches(task_id: str, wanted: str) -> bool:
    return task_id == wanted or task_id.startswith(wanted + "-")


def restrict(doc: dict, wanted: list[str]) -> dict:
    """The same results, keeping only the tasks named (by id or prefix such as c07)."""
    keep = [t for t in doc["task_ids"] if any(_matches(t, w.strip()) for w in wanted)]
    return {**doc, "task_ids": keep, "trials": [t for t in doc["trials"] if t["task_id"] in keep],
            "restricted_to": keep}


def first_trials(doc: dict, k: int) -> dict:
    """The same results, keeping only the first k trials of each task."""
    seen: Counter = Counter()
    kept = []
    for trial in doc["trials"]:
        seen[trial["task_id"]] += 1
        if seen[trial["task_id"]] <= k:
            kept.append(trial)
    return {**doc, "trials": kept, "trials_per_task": min(k, doc["trials_per_task"])}


def arm_name(doc: dict) -> str:
    return f"{doc['model']} · {doc['strategy']} · k{doc['trials_per_task']}"


# --- Statistics ----------------------------------------------------------------------

def pass_hat_k(c: int, n: int, k: int) -> float:
    if n < k:
        raise ValueError(f"pass^{k} needs at least {k} trials, got {n}.")
    return comb(c, k) / comb(n, k)


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact sign test on the tasks that differ. Ties are left out."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def min_one_sided_tasks(alpha: float = SIGNIFICANCE) -> int:
    """The fewest differing tasks, all one way, that a sign test can call significant."""
    n = 1
    while sign_test_p(n, 0) >= alpha:
        n += 1
    return n


def per_task(doc: dict) -> dict[str, tuple[int, int]]:
    """{task id: (successes, graded trials)}, error trials left out, in task-file order."""
    counts = {task_id: [0, 0] for task_id in doc["task_ids"]}
    for trial in doc["trials"]:
        if trial["success"] is None:
            continue
        entry = counts.setdefault(trial["task_id"], [0, 0])
        entry[0] += bool(trial["success"])
        entry[1] += 1
    return {task_id: (c, n) for task_id, (c, n) in counts.items() if n}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.0f}%"


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summary(doc: dict) -> dict:
    graded = [t for t in doc["trials"] if t["success"] is not None]
    tasks = per_task(doc)
    k = min((n for _, n in tasks.values()), default=0)
    runs = doc["trials"]

    def mean(values):
        return statistics.mean(values) if values else None

    return {
        "arm": arm_name(doc),
        "trials": len(runs),
        "graded": len(graded),
        "success": mean([bool(t["success"]) for t in graded]),
        "pass1": mean([c / n for c, n in tasks.values()]),
        "k": k,
        "pass_k": mean([pass_hat_k(c, n, k) for c, n in tasks.values()]) if k else None,
        "always": sum(1 for c, n in tasks.values() if c == n),
        "flaky": sum(1 for c, n in tasks.values() if 0 < c < n),
        "never": sum(1 for c, n in tasks.values() if c == 0),
        "groups": {g: mean([bool(t["verdict"]["groups"][g]) for t in graded]) for g in GROUPS},
        "calls": mean([t["model_calls"] for t in runs]),
        "tokens_in": mean([t["usage"].get("input_tokens", 0) for t in runs]),
        "tokens_out": mean([t["usage"].get("output_tokens", 0) for t in runs]),
        "cost": mean([t["cost_usd"] for t in runs]),
        "cost_total": sum(t["cost_usd"] for t in runs),
        "p50": _percentile([t["latency_ms"] for t in runs if t["latency_ms"]], 0.5) / 1000
               if any(t["latency_ms"] for t in runs) else None,
        "p95": _percentile([t["latency_ms"] for t in runs if t["latency_ms"]], 0.95) / 1000
               if any(t["latency_ms"] for t in runs) else None,
        "max_tokens": sum(t["max_tokens_endings"] for t in runs),
        # How runs ended, other than with a reply: step_cap, truncated, refused, no_reply...
        "exits": Counter(status for t in runs
                         if (status := (t.get("transcript") or {}).get("status"))
                         not in (None, "completed")),
        "errors": sum(1 for t in runs if t["error"]),
        "status": doc["status"],
    }


# --- Tables --------------------------------------------------------------------------

def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def summary_table(docs: list[dict]) -> str:
    header = ["arm", "trials", "success", "pass^1", "pass^k", "tasks always / flaky / never",
              "db ✓", "facts ✓", "hygiene ✓", "trajectory ✓", "model calls/run",
              "tokens in/run", "tokens out/run", "$/run", "$ total", "latency p50 / p95 s",
              "max_tokens endings", "other exits", "errors", "status"]
    rows = []
    for doc in docs:
        s = summary(doc)
        rows.append([
            s["arm"], s["trials"], _pct(s["success"]), _pct(s["pass1"]),
            f"{_pct(s['pass_k'])} (k={s['k']})", f"{s['always']} / {s['flaky']} / {s['never']}",
            *(_pct(s["groups"][g]) for g in GROUPS),
            f"{s['calls']:.2f}", f"{s['tokens_in']:.0f}", f"{s['tokens_out']:.0f}",
            f"{s['cost']:.6f}", f"{s['cost_total']:.4f}",
            f"{s['p50']:.1f} / {s['p95']:.1f}" if s["p50"] is not None else "–",
            s["max_tokens"],
            ", ".join(f"{name} {n}" for name, n in sorted(s["exits"].items())) or "–",
            s["errors"], s["status"],
        ])
    return _table(header, rows)


def category_table(docs: list[dict]) -> str:
    rows = []
    for doc in docs:
        by_cat = defaultdict(list)
        for t in doc["trials"]:
            if t["success"] is not None:
                by_cat[t["category"]].append(bool(t["success"]))
        rows.append([arm_name(doc)] + [
            f"{_pct(statistics.mean(by_cat[c]))} ({len(by_cat[c])})" if by_cat[c] else "–"
            for c in CATEGORIES])
    return _table(["arm", *(f"{c} (trials)" for c in CATEGORIES)], rows)


def variance_table(doc: dict) -> str:
    """Per task: successes out of trials, and which check failed most often."""
    failed: dict[str, Counter] = defaultdict(Counter)
    categories = {}
    for t in doc["trials"]:
        categories[t["task_id"]] = t["category"]
        for check in Verdict.from_dict(t["verdict"]).failed:
            failed[t["task_id"]][check.name] += 1
    rows = []
    for task_id, (c, n) in per_task(doc).items():
        top = failed[task_id].most_common(1)
        rows.append([task_id, categories.get(task_id, ""), f"{c}/{n}",
                     "flaky" if 0 < c < n else "",
                     f"{top[0][0]} ({top[0][1]}/{n})" if top else ""])
    return _table(["task", "category", "successes", "", "most frequent failed check"], rows)


def paired_table(a: dict, b: dict) -> str:
    """Arm A against arm B, task by task, on the per-task success rate.

    Arms with different trials per task are compared on the first min(k) trials of each
    task, so 4/5 against 1/1 is not counted as a win for the single trial.
    """
    matched = ""
    if a["trials_per_task"] != b["trials_per_task"]:
        k = min(a["trials_per_task"], b["trials_per_task"])
        matched = (f" The arms ran k={a['trials_per_task']} and k={b['trials_per_task']}, so "
                   f"each task is compared on its first {k} trial(s) only.")
        a, b = first_trials(a, k), first_trials(b, k)
    ta, tb = per_task(a), per_task(b)
    categories = {t["task_id"]: t["category"] for t in a["trials"] + b["trials"]}
    rows, wins, losses, ties = [], 0, 0, 0
    for task_id in [t for t in a["task_ids"] if t in ta and t in tb]:
        (ca, na), (cb, nb) = ta[task_id], tb[task_id]
        ra, rb = ca / na, cb / nb
        if ra > rb:
            outcome, wins = "A", wins + 1
        elif rb > ra:
            outcome, losses = "B", losses + 1
        else:
            outcome, ties = "tie", ties + 1
        rows.append([task_id, categories.get(task_id, ""), f"{ca}/{na}", f"{cb}/{nb}", outcome])
    p = sign_test_p(wins, losses)
    m = min_one_sided_tasks()
    verdict = "a finding" if p < SIGNIFICANCE else "a direction, not a finding"
    footer = (
        f"\nA = {arm_name(a)}, B = {arm_name(b)}. "
        f"A better on {wins} tasks, B better on {losses}, tied on {ties}. "
        f"Two-sided sign test p = {p:.3f}: {verdict}. "
        f"A sign test reaches p < {SIGNIFICANCE} only when at least {m} differing tasks all go "
        f"one way, so on {len(rows)} tasks a difference of less than about "
        f"{100 * m / max(len(rows), 1):.0f} points ({m} of {len(rows)} tasks) "
        "cannot be told from noise." + matched
    )
    return _table(["task", "category", "A", "B", "better"], rows) + "\n" + footer


def full_report(docs: list[dict]) -> str:
    parts = []
    regraded = [d for d in docs if d.get("regraded_with")]
    if regraded:
        parts.append(f"_Re-graded from the stored transcripts against task set "
                     f"{regraded[0]['regraded_with']} (recorded with "
                     f"{', '.join(sorted({d['task_set_hash'] for d in regraded}))})._")
    restricted = [d for d in docs if d.get("restricted_to") is not None]
    if restricted:
        parts.append(f"_Restricted to {len(restricted[0]['restricted_to'])} tasks: "
                     f"{', '.join(restricted[0]['restricted_to'])}._")
    parts += ["## Summary", summary_table(docs), "## Success by category", category_table(docs)]
    for doc in docs:
        if doc["trials_per_task"] > 1:
            parts += [f"## Per-task variance: {arm_name(doc)}", variance_table(doc)]
    for other in docs[1:]:
        parts += [f"## Paired: {arm_name(docs[0])} vs {arm_name(other)}",
                  paired_table(docs[0], other)]
    return "\n\n".join(parts) + "\n"


# --- One transcript, for reading ------------------------------------------------------

def show_trial(doc: dict, task_id: str, trial: int = 1) -> str:
    match = [t for t in doc["trials"]
             if (t["task_id"] == task_id or t["task_id"].startswith(task_id + "-"))
             and t["trial"] == trial]
    if not match:
        raise ValueError(f"No trial {trial} of {task_id} in {doc['sweep_id']}.")
    record = match[0]
    tr = Transcript.from_dict(record["transcript"])
    verdict = Verdict.from_dict(record["verdict"])
    task = by_id(load_tasks(doc["task_set"])).get(record["task_id"])
    out = [f"# {record['task_id']} · trial {trial} · {arm_name(doc)}",
           f"log: {record['log']}", "", "## Ticket", tr.ticket.strip(), ""]
    if task:
        out += [f"Expected: {task.expected.disposition}. {task.notes}", ""]
    for turn in tr.turns:
        out.append(f"## Model turn {turn.index}: stop {turn.stop} ({turn.provider_stop}), "
                   f"${turn.cost_usd:.6f}, {turn.latency_ms} ms")
        for call in [c for c in tr.tool_calls if c.turn == turn.index]:
            flag = " ERROR" if call.is_error else ""
            out.append(f"- {call.name}({call.arguments}){flag}")
            out.append(f"  → {json.dumps(call.result)}")
    out += ["", "## Reply", tr.reply or "(no reply)", "",
            "## Database change", json.dumps(tr.db_diff, indent=1) if tr.db_diff else "none", ""]
    if tr.error:
        out += [f"## Error\n{tr.error}", ""]
    result = {True: "SUCCESS", False: "FAIL", None: "ERROR (not graded)"}[verdict.success]
    out.append(f"## Verdict: {result}")
    out += [f"- [{'pass' if c.passed else 'FAIL'}] {c.group} · {c.name}: {c.detail}"
            for c in verdict.checks]
    return "\n".join(out) + "\n"
