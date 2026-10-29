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
from arl.evals.graders.attack import grade_attack
from arl.evals.safety import safety
from arl.evals.tasks import ADVERSARIAL_CATEGORIES, by_id, load_tasks, task_set_hash
from arl.evals.transcript import Transcript

CATEGORIES = ("read", "write", "refuse", "escalate")
SIGNIFICANCE = 0.05


# --- Loading -------------------------------------------------------------------------

def load_results(path: Path, regrade: bool = False) -> dict:
    """A results file. With `regrade`, every stored transcript is graded again against the
    task files as they are now, so a fixed phrase list or rule shows up without a re-run."""
    doc = json.loads(Path(path).read_text())
    sidecar = Path(path).with_suffix(".judge.json")
    if sidecar.exists():   # the advisory judge column, from `arl judge`
        doc["judge"] = json.loads(sidecar.read_text())
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
    present = {t["category"] for d in docs for t in d["trials"]}
    categories = (CATEGORIES if not present & set(ADVERSARIAL_CATEGORIES)
                  else tuple(c for c in CATEGORIES + ADVERSARIAL_CATEGORIES if c in present))
    rows = []
    for doc in docs:
        by_cat = defaultdict(list)
        for t in doc["trials"]:
            if t["success"] is not None:
                by_cat[t["category"]].append(bool(t["success"]))
        rows.append([arm_name(doc)] + [
            f"{_pct(statistics.mean(by_cat[c]))} ({len(by_cat[c])})" if by_cat[c] else "–"
            for c in categories])
    return _table(["arm", *(f"{c} (trials)" for c in categories)], rows)


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


def provenance_table(docs: list[dict]) -> str:
    """Success for the tasks written up front and the failure-derived ones, apart: the
    second group was chosen to be hard for the early rungs, so pooling them hides that."""
    provenance = {}
    for doc in [d for d in docs if d.get("task_set")]:
        for task in load_tasks(doc["task_set"]):
            provenance[task.id] = ("failure-derived" if task.provenance.startswith("failure-derived")
                                   else "original")
    rows = []
    for doc in docs:
        groups = defaultdict(list)
        for t in doc["trials"]:
            if t["success"] is not None:
                groups[provenance.get(t["task_id"], "original")].append(bool(t["success"]))
        tasks = defaultdict(set)
        for t in doc["trials"]:
            tasks[provenance.get(t["task_id"], "original")].add(t["task_id"])
        rows.append([arm_name(doc)] + [
            f"{_pct(statistics.mean(groups[g]))} ({len(tasks[g])} tasks, {len(groups[g])} trials)"
            if groups[g] else "–" for g in ("original", "failure-derived")])
    return _table(["arm", "original", "failure-derived"], rows)


def _judged(doc: dict) -> list[tuple[dict, dict]]:
    """(trial, judge verdict) pairs for the graded trials the judge saw."""
    verdicts = {(v["task_id"], v["trial"]): v for v in doc["judge"]["trials"]}
    return [(t, verdicts[(t["task_id"], t["trial"])]) for t in doc["trials"]
            if t["success"] is not None and (t["task_id"], t["trial"]) in verdicts]


def judge_table(docs: list[dict]) -> str:
    """The advisory judge column, beside the code facts check it is meant to complement.

    The judge never changes `success`. The corrected rate uses the held-out TPR and TNR,
    and is shown only when the sidecar was made with the validated prompt.
    """
    from arl.evals.judge_validation import corrected_pass_rate

    rows = []
    for doc in [d for d in docs if d.get("judge")]:
        pairs = _judged(doc)
        ok = [(t, v) for t, v in pairs if v["verdict"]]
        judge_pass = statistics.mean(v["verdict"] == "pass" for _, v in ok) if ok else None
        validation = doc["judge"].get("validation")
        corrected = (corrected_pass_rate(judge_pass, validation["tpr"], validation["tnr"])
                     if validation and judge_pass is not None
                     and validation.get("tpr") is not None and validation.get("tnr") is not None
                     else None)
        cells = Counter((bool(t["verdict"]["groups"]["facts"]), v["verdict"] == "pass")
                        for t, v in ok)
        rows.append([
            arm_name(doc), len(pairs), len(pairs) - len(ok), _pct(judge_pass), _pct(corrected),
            _pct(statistics.mean(bool(t["verdict"]["groups"]["facts"]) for t, _ in ok) if ok else None),
            cells[(True, True)], cells[(True, False)], cells[(False, True)], cells[(False, False)],
            doc["judge"]["prompt_hash"],
        ])
    return _table(["arm", "judged", "judge errors", "judge ✓ (advisory)", "corrected",
                   "code facts ✓", "facts ✓ judge ✓", "facts ✓ judge ✗", "facts ✗ judge ✓",
                   "facts ✗ judge ✗", "prompt"], rows)


def disagreements(doc: dict, limit: int = 20) -> str:
    """Trials where the code facts check and the judge disagree: the ones to read."""
    rows = [[t["task_id"], t["trial"], "pass" if t["verdict"]["groups"]["facts"] else "FAIL",
             v["verdict"], ", ".join(v["failure_codes"]) or "–", v["critique"].replace("|", "/")]
            for t, v in _judged(doc)
            if v["verdict"] and bool(t["verdict"]["groups"]["facts"]) != (v["verdict"] == "pass")]
    more = f"\n\n{len(rows) - limit} more not shown." if len(rows) > limit else ""
    return _table(["task", "trial", "code facts", "judge", "codes", "judge critique"],
                  rows[:limit]) + more


# --- Stage 5: attacks and safety ---------------------------------------------------------

def graded_trials(doc: dict) -> list[dict]:
    """Every graded trial with its attack verdict and safety counts, recomputed from the
    stored transcript against the task files, so --regrade covers them too."""
    tasks = by_id(load_tasks(doc["task_set"]))
    out = []
    for t in doc["trials"]:
        if t["success"] is None or t["task_id"] not in tasks:
            continue
        task, tr = tasks[t["task_id"]], Transcript.from_dict(t["transcript"])
        out.append({"trial": t, "task": task, "attack": grade_attack(task, tr),
                    "safety": safety(task, tr)})
    return out


def _rate(hits: int, n: int) -> str:
    from arl.evals.judge_validation import wilson

    if not n:
        return "–"
    ci = wilson(hits, n)
    return f"{100 * hits / n:.0f}% ({hits}/{n}; {100 * ci[0]:.0f}–{100 * ci[1]:.0f})"


def is_adversarial(doc: dict) -> bool:
    return any(t["category"] in ADVERSARIAL_CATEGORIES for t in doc["trials"])


def attack_table(docs: list[dict]) -> str:
    """Per arm: how often attacks landed, were tried, and how often the real request was done."""
    rows = []
    for doc in [d for d in docs if is_adversarial(d)]:
        g = graded_trials(doc)
        n = len(g)
        harmed = sum(x["attack"].harmed for x in g)
        tried = sum(x["attack"].attempted for x in g)
        rows.append([
            arm_name(doc), n, _rate(harmed, n), _rate(tried, n),
            f"{tried - harmed}", _rate(sum(x["attack"].utility for x in g), n),
            _rate(sum(bool(x["trial"]["success"]) for x in g), n),
            f"{statistics.mean(x['trial']['model_calls'] for x in g):.2f}" if g else "–",
            f"{statistics.mean(x['trial']['cost_usd'] for x in g):.6f}" if g else "–",
        ])
    return _table(["arm", "trials", "attack success (harm), 95% CI", "attempted (took the bait)",
                   "caught (attempted, no harm)", "utility (legitimate request done)",
                   "strict success",
                   "model calls/run", "$/run"], rows)


def attack_category_table(docs: list[dict]) -> str:
    rows = []
    for doc in [d for d in docs if is_adversarial(d)]:
        by_cat = defaultdict(list)
        for x in graded_trials(doc):
            by_cat[x["task"].category].append(x["attack"].harmed)
        rows.append([arm_name(doc)] + [
            f"{_pct(statistics.mean(by_cat[c]))} ({sum(by_cat[c])}/{len(by_cat[c])})"
            if by_cat[c] else "–" for c in ADVERSARIAL_CATEGORIES])
    return _table(["arm (harm rate)", *ADVERSARIAL_CATEGORIES], rows)


def attack_task_table(docs: list[dict]) -> str:
    """Per task and arm: harm / attempted / utility, out of the graded trials."""
    docs = [d for d in docs if is_adversarial(d)]
    cells: dict[str, dict[str, str]] = defaultdict(dict)
    categories = {}
    for doc in docs:
        by_task = defaultdict(list)
        for x in graded_trials(doc):
            by_task[x["task"].id].append(x)
            categories[x["task"].id] = x["task"].category
        for task_id, xs in by_task.items():
            n = len(xs)
            cells[task_id][arm_name(doc)] = (
                f"{sum(x['attack'].harmed for x in xs)} / {sum(x['attack'].attempted for x in xs)}"
                f" / {sum(x['attack'].utility for x in xs)} of {n}")
    order = [t for d in docs for t in d["task_ids"]]
    task_ids = list(dict.fromkeys(t for t in order if t in cells))
    rows = [[t, categories[t], *(cells[t].get(arm_name(d), "–") for d in docs)] for t in task_ids]
    return _table(["task", "category", *(f"{arm_name(d)}: harm / tried / utility" for d in docs)],
                  rows)


def paired_harm_table(a: dict, b: dict) -> str:
    """Arm A against arm B on each task's harm rate. Lower harm is better."""
    def harm_by_task(doc):
        out = defaultdict(list)
        for x in graded_trials(doc):
            out[x["task"].id].append(x["attack"].harmed)
        return out

    k = min(a["trials_per_task"], b["trials_per_task"])
    ha, hb = harm_by_task(first_trials(a, k)), harm_by_task(first_trials(b, k))
    rows, wins, losses, ties = [], 0, 0, 0
    for task_id in [t for t in a["task_ids"] if ha.get(t) and hb.get(t)]:
        ra, rb = statistics.mean(ha[task_id]), statistics.mean(hb[task_id])
        better = "A" if ra < rb else "B" if rb < ra else "tie"
        wins, losses, ties = wins + (better == "A"), losses + (better == "B"), ties + (better == "tie")
        rows.append([task_id, f"{sum(ha[task_id])}/{len(ha[task_id])}",
                     f"{sum(hb[task_id])}/{len(hb[task_id])}", better])
    p = sign_test_p(wins, losses)
    m = min_one_sided_tasks()
    verdict = "a finding" if p < SIGNIFICANCE else "a direction, not a finding"
    return (_table(["task", "A harm", "B harm", "less harm"], rows) +
            f"\nA = {arm_name(a)}, B = {arm_name(b)}. Less harm in A on {wins} tasks, in B on "
            f"{losses}, tied on {ties}. Two-sided sign test p = {p:.3f}: {verdict}. At least {m} "
            f"differing tasks, all one way, are needed for p < {SIGNIFICANCE}.")


def still_succeeding(docs: list[dict]) -> str:
    """The attacks that landed at least once, per arm, with one example of how."""
    lines = []
    for doc in [d for d in docs if is_adversarial(d)]:
        landed = defaultdict(list)
        for x in graded_trials(doc):
            if x["attack"].harmed:
                landed[x["task"].id].append(x)
        lines.append(f"- **{arm_name(doc)}**: " + ("none" if not landed else "; ".join(
            f"{task_id} {len(xs)}× ({xs[0]['task'].attack.goal}: {xs[0]['attack'].detail})"
            for task_id, xs in landed.items())))
    return "\n".join(lines)


def safety_table(docs: list[dict]) -> str:
    rows = []
    for doc in docs:
        g = graded_trials(doc)
        n = len(g)
        exits = Counter(x["safety"].status for x in g)
        rows.append([
            arm_name(doc), n,
            _rate(sum(bool(x["safety"].unsafe) for x in g), n),
            _rate(sum(bool(x["safety"].double) for x in g), n),
            _rate(sum(x["safety"].runaway for x in g), n),
            exits.get("loop_detected", 0),
            ", ".join(f"{s} {c}" for s, c in sorted(exits.items(), key=lambda i: str(i[0]))
                      if s not in (None, "completed")) or "–",
        ])
    return _table(["arm", "graded trials", "unsafe action", "double write",
                   "runaway (step cap or budget)", "loop detected", "other exits"], rows)


# --- Stage 7: approvals --------------------------------------------------------------------

def has_approvals(doc: dict) -> bool:
    return any((t.get("approvals") or {}).get("requests") for t in doc["trials"])


def _approvals(trial: dict) -> dict:
    return trial.get("approvals") or {"requests": 0, "flagged_calls": 0, "approved": 0,
                                      "rejected": 0, "reviews": []}


def approval_table(docs: list[dict]) -> str:
    """The reviewer's load per arm. An arm without a gate shows zeros."""
    rows = []
    for doc in docs:
        trials = [t for t in doc["trials"] if t["success"] is not None]
        n = len(trials)
        a = [_approvals(t) for t in trials]
        requests, flagged = sum(x["requests"] for x in a), sum(x["flagged_calls"] for x in a)
        rows.append([arm_name(doc), n, requests, f"{100 * requests / n:.1f}" if n else "–",
                     f"{100 * flagged / n:.1f}" if n else "–",
                     sum(x["approved"] for x in a), sum(x["rejected"] for x in a),
                     sum(1 for x in a if x["requests"])])
    return _table(["arm", "graded trials", "approval requests",
                   "requests per 100 tickets", "flagged calls per 100 tickets", "approved",
                   "rejected", "trials with a request"], rows)


def approval_task_table(docs: list[dict]) -> str:
    """Per task and arm: requests, and approved / rejected calls."""
    docs = [d for d in docs if has_approvals(d)]
    cells: dict[str, dict[str, str]] = defaultdict(dict)
    for doc in docs:
        by_task = defaultdict(list)
        for t in doc["trials"]:
            by_task[t["task_id"]].append(_approvals(t))
        for task_id, xs in by_task.items():
            if any(x["requests"] for x in xs):
                cells[task_id][arm_name(doc)] = (
                    f"{sum(x['requests'] for x in xs)} req: {sum(x['approved'] for x in xs)} "
                    f"approved, {sum(x['rejected'] for x in xs)} rejected of {len(xs)} trials")
    order = list(dict.fromkeys(t for d in docs for t in d["task_ids"] if t in cells))
    return _table(["task", *(arm_name(d) for d in docs)],
                  [[t, *(cells[t].get(arm_name(d), "–") for d in docs)] for t in order])


def _is_attack(task, call: dict) -> bool:
    """Does a reviewed call match one of the task's attack attempts?"""
    from arl.evals.graders.attack import _args_match
    from arl.evals.transcript import ToolCallRecord

    if task is None or task.attack is None:
        return False
    args = call["arguments"]
    record = ToolCallRecord(0, call["tool"], args if isinstance(args, str) else json.dumps(args),
                            {}, False)
    return any(spec.tool == call["tool"] and _args_match(spec.args, record)
               for spec in task.attack.attempt)


def reviewer_replay_table(docs: list[dict]) -> str:
    """Counterfactual: the logged packets shown to other reviewers. It counts what each would
    have approved, not what the run would then have done (a different answer changes the
    rest of the run). An approved attack call is a write the gate would have let through,
    subject to the invariants and grounding after it."""
    from arl.framework.approval import REPLAY_REVIEWERS

    rows = []
    for doc in [d for d in docs if has_approvals(d)]:
        tasks = by_id(load_tasks(doc["task_set"]))
        reviewed = [(tasks.get(t["task_id"]), review["packet"], call)
                    for t in doc["trials"] for review in _approvals(t)["reviews"]
                    for call in review["packet"]["calls"]]
        for name, reviewer in REPLAY_REVIEWERS.items():
            approved = attacks = attacks_approved = 0
            for task, packet, call in reviewed:
                verdict = reviewer.review({**packet, "calls": [call]})[call["call_id"]]
                is_attack = _is_attack(task, call)
                approved += verdict["decision"] == "approve"
                attacks += is_attack
                attacks_approved += is_attack and verdict["decision"] == "approve"
            rows.append([arm_name(doc), name, len(reviewed), approved,
                         f"{attacks_approved} of {attacks}",
                         f"{approved - attacks_approved} of {len(reviewed) - attacks}"])
    return _table(["arm", "reviewer (replayed)", "flagged calls", "approved",
                   "attack calls approved", "other calls approved"], rows)


def paired_utility_table(a: dict, b: dict) -> str:
    """Arm A against arm B on each adversarial task's utility rate. Higher is better."""
    def utility_by_task(doc):
        out = defaultdict(list)
        for x in graded_trials(doc):
            out[x["task"].id].append(x["attack"].utility)
        return out

    k = min(a["trials_per_task"], b["trials_per_task"])
    ua, ub = utility_by_task(first_trials(a, k)), utility_by_task(first_trials(b, k))
    rows, wins, losses, ties = [], 0, 0, 0
    for task_id in [t for t in a["task_ids"] if ua.get(t) and ub.get(t)]:
        ra, rb = statistics.mean(ua[task_id]), statistics.mean(ub[task_id])
        better = "A" if ra > rb else "B" if rb > ra else "tie"
        wins, losses, ties = wins + (better == "A"), losses + (better == "B"), ties + (better == "tie")
        rows.append([task_id, f"{sum(ua[task_id])}/{len(ua[task_id])}",
                     f"{sum(ub[task_id])}/{len(ub[task_id])}", better])
    p = sign_test_p(wins, losses)
    verdict = "a finding" if p < SIGNIFICANCE else "a direction, not a finding"
    return (_table(["task", "A utility", "B utility", "more utility"], rows) +
            f"\nA = {arm_name(a)}, B = {arm_name(b)}. More utility in A on {wins} tasks, in B on "
            f"{losses}, tied on {ties}. Two-sided sign test p = {p:.3f}: {verdict}.")


# --- Multi-agent cost (Stage 8) -----------------------------------------------------------

def _tokens(trial: dict) -> int:
    """Input (cached included) + output, over every model call of every agent in the run."""
    return trial["usage"].get("input_tokens", 0) + trial["usage"].get("output_tokens", 0)


def _uncached(trial: dict) -> int:
    return trial["usage"].get("input_tokens", 0) - trial["usage"].get("cached_input_tokens", 0)


def _task_means(doc: dict, metric) -> dict[str, float]:
    by_task: dict[str, list] = defaultdict(list)
    for trial in doc["trials"]:
        if not trial["error"]:
            by_task[trial["task_id"]].append(metric(trial))
    return {task: statistics.mean(values) for task, values in by_task.items()}


def multiplier(ref: dict, arm: dict, metric) -> tuple[float | None, int]:
    """sum over tasks of the arm's per-task mean / the same sum for the reference, on the
    tasks both ran, matched on k (the first min(k) trials). Returns (ratio, tasks)."""
    k = min(ref["trials_per_task"], arm["trials_per_task"])
    a, b = _task_means(first_trials(arm, k), metric), _task_means(first_trials(ref, k), metric)
    common = [t for t in b if t in a]
    base = sum(b[t] for t in common)
    return (sum(a[t] for t in common) / base if base else None), len(common)


def has_agents(doc: dict) -> bool:
    return any(t.get("agents") for t in doc["trials"])


def multiplier_table(docs: list[dict]) -> str:
    """Each arm against the first, per run and paired by task: tokens, dollars, model
    calls, uncached input and p50 latency, as multiples of the reference."""
    ref = docs[0]
    metrics = {"tokens": _tokens, "$": lambda t: t["cost_usd"],
               "model calls": lambda t: t["model_calls"], "uncached input": _uncached}
    rows = []
    for doc in docs:
        cells, n = [], 0
        for metric in metrics.values():
            ratio, n = multiplier(ref, doc, metric)
            cells.append("–" if ratio is None else f"{ratio:.2f}×")
        k = min(ref["trials_per_task"], doc["trials_per_task"])
        p50 = [summary(first_trials(d, k))["p50"] for d in (ref, doc)]
        cells.append(f"{p50[1] / p50[0]:.2f}×" if all(p50) else "–")
        mean_tokens = statistics.mean([_tokens(t) for t in doc["trials"] if not t["error"]] or [0])
        max_tokens = max([_tokens(t) for t in doc["trials"]] or [0])
        rows.append([arm_name(doc), n, *cells, f"{mean_tokens:,.0f}", f"{max_tokens:,}"])
    return (_table(["arm", "tasks paired", "token multiplier", "cost multiplier",
                    "model-call multiplier", "uncached-input multiplier", "p50 latency ratio",
                    "tokens/run", "max tokens in a run"], rows)
            + f"\nReference = {arm_name(ref)}. A multiplier is the sum over the paired tasks "
              "of the arm's mean per run, divided by the same sum for the reference, on the "
              "first min(k) trials of each task. Tokens are input (cached included) plus "
              "output, over every model call of every agent.")


def agent_table(docs: list[dict]) -> str:
    """Where a multi-agent arm's calls, tokens and dollars went, by agent."""
    rows = []
    for doc in [d for d in docs if has_agents(d)]:
        runs = [t for t in doc["trials"] if t.get("agents") and not t["error"]]
        totals: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        for t in runs:
            for name, a in t["agents"]["agents"].items():
                for key, value in a.items():
                    totals[name][key] += value
        all_tokens = sum(a["input_tokens"] + a["output_tokens"] for a in totals.values()) or 1
        all_cost = sum(a["cost_usd"] for a in totals.values()) or 1
        for name, a in sorted(totals.items(), key=lambda kv: -kv[1]["cost_usd"]):
            tokens = a["input_tokens"] + a["output_tokens"]
            rows.append([arm_name(doc), name, f"{a['model_calls'] / len(runs):.2f}",
                         f"{tokens / len(runs):,.0f}", _pct(tokens / all_tokens),
                         _pct(a["cached_input_tokens"] / a["input_tokens"])
                         if a["input_tokens"] else "–",
                         f"${a['cost_usd'] / len(runs):.6f}", _pct(a["cost_usd"] / all_cost)])
    return _table(["arm", "agent", "calls/run", "tokens/run", "share of tokens", "cached",
                   "$/run", "share of $"], rows)


def coordination_table(docs: list[dict]) -> str:
    """The work of coordinating: delegations or handoffs, repeated lookups, and how much the
    specialists asked together overlapped in time."""
    rows = []
    for doc in [d for d in docs if has_agents(d)]:
        runs = [t["agents"] for t in doc["trials"] if t.get("agents") and not t["error"]]
        batches = [b for r in runs for b in r["batches"]]
        together = [b for b in batches if b["specialists"] > 1]
        wall, total = sum(b["wall_ms"] for b in together), sum(b["sum_ms"] for b in together)
        rows.append([arm_name(doc), f"{statistics.mean(r['delegations'] for r in runs):.2f}",
                     f"{statistics.mean(r['handoffs'] for r in runs):.2f}",
                     f"{statistics.mean(r['duplicate_reads'] for r in runs):.2f}",
                     f"{statistics.mean(b['specialists'] for b in batches):.2f}"
                     if batches else "–",
                     f"{len(together)}",
                     f"{wall / 1000:.1f} s of {total / 1000:.1f} s" if together else "–"])
    return (_table(["arm", "delegations/run", "handoffs/run", "repeated lookups/run",
                    "specialists per turn", "turns with several", "their wall time vs the sum"],
                   rows)
            + "\nRepeated lookups: successful read calls in a run identical to an earlier one "
              "(same tool and arguments), by any agent.")


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
    if any(t.provenance.startswith("failure-derived")
           for d in docs if d.get("task_set") for t in load_tasks(d["task_set"])
           if t.id in d["task_ids"]):
        parts += ["## Original and failure-derived tasks", provenance_table(docs)]
    if any(d.get("judge") for d in docs):
        parts += ["## Reply judge (advisory, not part of success)", judge_table(docs)]
        for doc in [d for d in docs if d.get("judge")]:
            parts += [f"### Code facts and judge disagree: {arm_name(doc)}", disagreements(doc)]
    if any(d.get("phase") == "phase-5" or is_adversarial(d) for d in docs):
        parts += ["## Safety (code-checked)", safety_table(docs)]
    adversarial = [d for d in docs if is_adversarial(d)]
    if adversarial:
        parts += ["## Attacks", attack_table(adversarial),
                  "## Attack success by category", attack_category_table(adversarial),
                  "## Attacks by task", attack_task_table(adversarial),
                  "## Attacks that still succeed", still_succeeding(adversarial)]
        for other in adversarial[1:]:
            parts += [f"## Paired harm: {arm_name(adversarial[0])} vs {arm_name(other)}",
                      paired_harm_table(adversarial[0], other)]
            if has_approvals(other) or has_approvals(adversarial[0]):
                parts += [f"## Paired utility: {arm_name(adversarial[0])} vs {arm_name(other)}",
                          paired_utility_table(adversarial[0], other)]
    if any(has_approvals(d) for d in docs):
        parts += ["## Approvals (reviewer load)", approval_table(docs),
                  "## Approvals by task", approval_task_table(docs),
                  "## Other reviewers, replayed on the logged packets (counterfactual)",
                  reviewer_replay_table(docs)]
    if any(has_agents(d) for d in docs):
        parts += ["## Multi-agent cost against the first arm", multiplier_table(docs),
                  "## Where the calls and tokens went, by agent", agent_table(docs),
                  "## Coordination", coordination_table(docs)]
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
