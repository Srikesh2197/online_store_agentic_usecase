"""Run tasks through the agent, k trials each, under a hard cost cap.

    estimate   expected and worst-case cost, before anything is spent
    sweep      for each task, for each trial: a fresh store, one run, the end state, a grade
    cap        before each trial, stop if the worst case of that trial could cross the cap
    record     one results JSON per sweep and one ledger row, written even on a halt

The agent under test is `run_single_round`, unchanged. The runner only gives it a fresh
store and a tracer, and afterwards records what the store looks like.
"""

import csv
import json
import statistics
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from arl import ROOT
from arl.env.seed import new_store
from arl.env.tools import tool_specs
from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.tasks import DEFAULT_SET, Task, task_set_hash
from arl.evals.transcript import Transcript
from arl.foundations.single_round import (
    MAX_OUTPUT_TOKENS,
    STRATEGY,
    build_instructions,
    run_single_round,
)
from arl.llm.pricing import model_entry, price_for
from arl.llm.types import Message, Text
from arl.tracing.tracer import RUNS_DIR, Tracer, read_events

RESULTS_DIR = ROOT / "results"
LEDGER_NAME = "spend.csv"
EVAL_RUNS_DIR = RUNS_DIR / "eval"
PHASE = "phase-2"
PHASE_BUDGET_USD = 1.50

CALLS_PER_TRIAL = 2              # the single round: request 1, then request 2 if tools ran
# Request characters per input token, measured from the recorded t1 bodies in
# tests/fixtures/recorded/ (OpenAI 10,515 chars = 1,834 tokens; Anthropic 10,351 = 3,681,
# which includes its hidden tool prompt). A test keeps these in line with the fixtures.
CHARS_PER_TOKEN = {"openai": 5.7, "anthropic": 2.8}
PRIOR_OUTPUT_TOKENS_PER_CALL = 400   # until a sweep of the model has been measured
WORST_TOOL_RESULT_TOKENS = 600       # what request 2 adds at most for tool results
MAX_CONSECUTIVE_ERRORS = 3
MAX_LANGFUSE_TRACES = 30

LEDGER_FIELDS = [
    "ts_utc", "sweep_id", "phase", "strategy", "model", "task_set", "tasks",
    "trials_per_task", "trials_planned", "trials_run", "est_usd", "worst_usd", "cap_usd",
    "spent_usd", "status", "results_file", "git_commit",
]


# --- Estimate ----------------------------------------------------------------------

@dataclass(frozen=True)
class Estimate:
    model: str
    trials: int
    input_tokens_per_call: int    # mean over the tasks, for request 1
    per_trial_expected: float
    per_trial_worst: float
    basis: str                    # where per_trial_expected comes from

    @property
    def expected_usd(self) -> float:
        return self.trials * self.per_trial_expected

    @property
    def worst_usd(self) -> float:
        return self.trials * self.per_trial_worst


def _adapter_class(provider: str):
    if provider == "openai":
        from arl.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter
    from arl.llm.anthropic_adapter import AnthropicAdapter
    return AnthropicAdapter


def request_chars(model: str, ticket: str) -> int:
    """The size of request 1 for this ticket, built exactly as it would be sent."""
    entry = model_entry(model)
    adapter = _adapter_class(entry["provider"])(model, send=None,
                                                options=entry.get("request_options"))
    request = adapter.build_request(
        system=build_instructions(), messages=[Message("user", [Text(ticket.strip())])],
        tools=tool_specs(), tool_choice="auto", max_tokens=MAX_OUTPUT_TOKENS,
    )
    return len(json.dumps(request))


def measured_trial_costs(model: str, results_dir: Path = RESULTS_DIR,
                         strategy: str = STRATEGY) -> list[float]:
    costs = []
    for path in sorted(Path(results_dir).glob("*.json")):
        doc = json.loads(path.read_text())
        if doc.get("model") == model and doc.get("strategy") == strategy:
            costs += [t["cost_usd"] for t in doc["trials"] if not t["error"]]
    return costs


def estimate(tasks: list[Task], model: str, trials_per_task: int,
             results_dir: Path = RESULTS_DIR) -> Estimate:
    provider = model_entry(model)["provider"]
    price = price_for(model)
    tokens = statistics.mean(request_chars(model, t.ticket) / CHARS_PER_TOKEN[provider]
                             for t in tasks)
    input_price = max(price.input, price.cache_write or 0.0)   # no cache discount assumed
    worst = CALLS_PER_TRIAL * ((tokens + WORST_TOOL_RESULT_TOKENS) * input_price
                               + MAX_OUTPUT_TOKENS * price.output) / 1e6
    measured = measured_trial_costs(model, results_dir)
    if measured:
        expected = statistics.mean(measured)
        basis = f"measured: mean of {len(measured)} earlier trials of {model}"
    else:
        expected = CALLS_PER_TRIAL * (tokens * input_price
                                      + PRIOR_OUTPUT_TOKENS_PER_CALL * price.output) / 1e6
        basis = (f"prior: {round(tokens)} input tokens per call from the request size, "
                 f"{PRIOR_OUTPUT_TOKENS_PER_CALL} output tokens per call, no cache")
    return Estimate(model, len(tasks) * trials_per_task, round(tokens), expected, worst, basis)


# --- Ledger --------------------------------------------------------------------------

def read_ledger(results_dir: Path = RESULTS_DIR) -> list[dict]:
    path = Path(results_dir) / LEDGER_NAME
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def phase_spent(results_dir: Path = RESULTS_DIR, phase: str = PHASE) -> float:
    return sum(float(row["spent_usd"]) for row in read_ledger(results_dir)
               if row["phase"] == phase)


def append_ledger(row: dict, results_dir: Path = RESULTS_DIR) -> None:
    path = Path(results_dir) / LEDGER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit}-dirty" if dirty else commit


# --- Trials --------------------------------------------------------------------------

_BASELINE: dict | None = None


def _baseline() -> dict:
    """The seeded store before any run. The seed is deterministic, so it is computed once."""
    global _BASELINE
    if _BASELINE is None:
        conn = new_store()
        _BASELINE = snapshot(conn)
        conn.close()
    return _BASELINE


def run_trial(task: Task, trial: int, *, adapter, sweep_id: str, runs_dir: Path,
              langfuse=None) -> dict:
    """One attempt at one task. API failures become an error trial; Ctrl-C propagates."""
    run_id = f"{sweep_id}-{task.id}-k{trial}"
    tracer = Tracer(run_id, log_dir=Path(runs_dir) / sweep_id, langfuse=langfuse, phase=PHASE)
    conn = new_store()
    error = None
    try:
        run_single_round(task.ticket.strip(), ticket_id=task.id, conn=conn, adapter=adapter,
                         tracer=tracer)
    except Exception as exc:  # noqa: BLE001 -- an API or harness failure, not a wrong answer
        error = f"{type(exc).__name__}: {exc}"
    finally:
        tracer.event("end_state", db_diff=diff(_baseline(), snapshot(conn)))
        conn.close()
    events = read_events(tracer.path)
    if any(e["type"] == "run_start" for e in events):
        transcript = Transcript.from_events(events)
    else:  # failed before the run started, so only the end state was logged
        transcript = Transcript(task.id, task.ticket, adapter.model, STRATEGY,
                                db_diff=events[-1]["db_diff"])
    if error and not transcript.error:
        transcript = replace(transcript, error=error)
    verdict = grade(task, transcript)
    return {
        "task_id": task.id,
        "category": task.category,
        "trial": trial,
        "run_id": run_id,
        "log": str(tracer.path.relative_to(ROOT)) if tracer.path.is_relative_to(ROOT)
               else str(tracer.path),
        "success": verdict.success,
        "error": transcript.error,
        "model_calls": len(transcript.turns),
        "tool_calls": len(transcript.tool_calls),
        "usage": transcript.usage,
        "cost_usd": transcript.cost_usd,
        "latency_ms": transcript.latency_ms,
        "stop": transcript.stop,
        "max_tokens_endings": sum(1 for t in transcript.turns if t.stop == "max_tokens"),
        "verdict": verdict.to_dict(),
        "transcript": transcript.to_dict(),
    }


# --- Sweep ---------------------------------------------------------------------------

def new_sweep_id(model: str, trials: int, strategy: str = STRATEGY) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{strategy}-{model}-k{trials}"


def run_sweep(tasks: list[Task], *, adapter, trials_per_task: int, cap_usd: float,
              est: Estimate, task_set: str = DEFAULT_SET, results_dir: Path = RESULTS_DIR,
              runs_dir: Path = EVAL_RUNS_DIR, langfuse=None, sweep_id: str | None = None,
              progress=lambda record, spent: None) -> dict:
    """Run every task `trials_per_task` times, task-major, and record the results.

    Before each trial, if what has been spent plus that trial's worst case would cross
    `cap_usd`, the sweep halts. Spend is read from the model calls actually logged, so a
    trial that crashed after one call still counts.
    """
    sweep_id = sweep_id or new_sweep_id(adapter.model, trials_per_task)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    records: list[dict] = []
    spent, status, consecutive_errors = 0.0, "completed", 0
    plan = [(task, k) for task in tasks for k in range(1, trials_per_task + 1)]
    try:
        for task, k in plan:
            if spent + est.per_trial_worst > cap_usd:
                status = "halted_cap"
                break
            mirror = langfuse if langfuse is not None and len(records) < MAX_LANGFUSE_TRACES else None
            record = run_trial(task, k, adapter=adapter, sweep_id=sweep_id, runs_dir=runs_dir,
                               langfuse=mirror)
            records.append(record)
            spent += record["cost_usd"]
            progress(record, spent)
            consecutive_errors = consecutive_errors + 1 if record["error"] else 0
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                status = "halted_errors"
                break
    except KeyboardInterrupt:
        status = "interrupted"
    finally:
        results_file = results_dir / f"{sweep_id}.json"
        commit = git_commit()
        doc = {
            "sweep_id": sweep_id,
            "phase": PHASE,
            "strategy": STRATEGY,
            "model": adapter.model,
            "provider": adapter.provider,
            "task_set": task_set,
            "task_set_hash": task_set_hash(task_set),
            "task_ids": [t.id for t in tasks],
            "trials_per_task": trials_per_task,
            "trials_planned": len(plan),
            "trials_run": len(records),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "prices": asdict(price_for(adapter.model)),
            "estimate": {**asdict(est), "expected_usd": est.expected_usd,
                         "worst_usd": est.worst_usd},
            "cap_usd": cap_usd,
            "spent_usd": spent,
            "status": status,
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": commit,
            "trials": records,
        }
        results_file.write_text(json.dumps(doc, indent=1) + "\n")
        append_ledger({
            "ts_utc": doc["finished_at"], "sweep_id": sweep_id, "phase": PHASE,
            "strategy": STRATEGY, "model": adapter.model, "task_set": task_set,
            "tasks": len(tasks), "trials_per_task": trials_per_task,
            "trials_planned": len(plan), "trials_run": len(records),
            "est_usd": f"{est.expected_usd:.6f}", "worst_usd": f"{est.worst_usd:.6f}",
            "cap_usd": f"{cap_usd:.4f}", "spent_usd": f"{spent:.6f}", "status": status,
            "results_file": results_file.name, "git_commit": commit,
        }, results_dir)
    return doc
