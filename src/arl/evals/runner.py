"""Run tasks through the agent, k trials each, under a hard cost cap.

    estimate   expected and worst-case cost, before anything is spent
    sweep      for each task, for each trial: a fresh store, one run, the end state, a grade
    cap        before each trial, stop if the worst case of that trial could cross the cap
    record     one results JSON per sweep and one ledger row, written even on a halt

The agent under test is a strategy: rung 1 (`single_round`), rung 2 (`hand_loop`), each
unchanged, rung 2 with guardrails (`guarded_prompt`, `guarded_all`, Stage 5), or the Stage 6
framework strategies on LangGraph: the graph agent (`graph_off`, `graph_all`) and the
workflow (`workflow`), and the Stage 7 graph agent with an approval gate answered by the
scripted reviewer (`graph_approve_all`, `graph_approve_risk`). The runner gives it a fresh store with the task's environment (its
setup, faults and sender, and the arm's invariants) and a tracer, and afterwards records what
the store looks like. Every strategy is graded from the same trace events.
"""

import csv
import json
import statistics
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from arl import ROOT
from arl.env.store import env_of
from arl.env.tools import tool_specs
from arl.evals.dbdiff import diff, snapshot
from arl.evals.graders import grade
from arl.evals.graders.attack import grade_attack
from arl.evals.safety import safety
from arl.evals.tasks import DEFAULT_SET, Task, task_set_hash
from arl.evals.transcript import Transcript
from arl.evals.trial_env import trial_store
from arl.foundations.guarded_loop import run_guarded_loop
from arl.foundations.hand_loop import MAX_STEPS, run_hand_loop
from arl.foundations.single_round import (
    MAX_OUTPUT_TOKENS,
    build_instructions,
    run_single_round,
)
from arl.guardrails import PROFILES
from arl.llm.pricing import model_entry, price_for
from arl.llm.types import Message, Text
from arl.tracing.tracer import RUNS_DIR, Tracer, read_events

RESULTS_DIR = ROOT / "results"
LEDGER_NAME = "spend.csv"
EVAL_RUNS_DIR = RUNS_DIR / "eval"
PHASE = "phase-7"
PHASE_BUDGET_USD = 1.00


@dataclass(frozen=True)
class Strategy:
    name: str
    run: Callable
    max_calls: int     # model calls a trial can make at most: the basis of the worst case
    prior_calls: int   # model calls a trial is expected to make, until one has been measured
    invariants: bool = False       # the write tools enforce the policy invariants (Stage 5)
    cost_basis: str | None = None  # another strategy whose measured cost to borrow until
                                   # this one has its own
    max_usd: float | None = None   # a per-run dollar budget, which bounds the worst case


def _guarded(profile: str, **fields) -> Strategy:
    guards = PROFILES[profile]
    return Strategy(profile, partial(run_guarded_loop, guards=guards),
                    max_calls=MAX_STEPS + (1 if guards.truncation_retry else 0), prior_calls=4,
                    invariants=guards.invariants, cost_basis="hand_loop",
                    max_usd=guards.limits.max_usd if guards.limits else None, **fields)


def _graph(profile: str, name: str, cost_basis: str) -> Strategy:
    """Rung 3: the graph agent with a Stage 5 profile. Imported on first use, so the
    foundations run without the framework extra installed."""
    guards = PROFILES[profile]

    def run(ticket, **kwargs):
        from arl.framework.graph_agent import run_graph_agent
        return run_graph_agent(ticket, guards=guards, strategy=name, **kwargs)

    return Strategy(name, run, max_calls=MAX_STEPS + (1 if guards.truncation_retry else 0),
                    prior_calls=4, invariants=guards.invariants, cost_basis=cost_basis,
                    max_usd=guards.limits.max_usd if guards.limits else None)


def _workflow() -> Strategy:
    guards = PROFILES["guarded_all"]

    def run(ticket, **kwargs):
        from arl.framework.workflow import run_workflow
        return run_workflow(ticket, guards=guards, **kwargs)

    # route, pick, decide, reply and one truncation retry
    return Strategy("workflow", run, max_calls=5, prior_calls=3, invariants=guards.invariants,
                    cost_basis="hand_loop", max_usd=guards.limits.max_usd)


def _approval(name: str, policy: str) -> Strategy:
    """Stage 7: the graph agent with every guardrail on and an approval gate. The scripted
    reviewer answers each pause in the same process; the checkpoints of a sweep go to one
    SQLite file beside its traces."""
    guards = PROFILES["guarded_all"]

    def run(ticket, **kwargs):
        from arl.framework.approval import POLICIES, ScriptedReviewer
        from arl.framework.graph_agent import run_graph_agent
        from arl.framework.threads import checkpointer

        saver = checkpointer(str(kwargs["tracer"].path.parent / "checkpoints.sqlite"))
        return run_graph_agent(ticket, guards=guards, strategy=name, policy=POLICIES[policy],
                               reviewer=ScriptedReviewer(), checkpointer=saver, **kwargs)

    return Strategy(name, run, max_calls=MAX_STEPS + (1 if guards.truncation_retry else 0),
                    prior_calls=4, invariants=guards.invariants, cost_basis="graph_all",
                    max_usd=guards.limits.max_usd if guards.limits else None)


STRATEGIES = {
    "single_round": Strategy("single_round", run_single_round, max_calls=2, prior_calls=2),
    "hand_loop": Strategy("hand_loop", run_hand_loop, max_calls=MAX_STEPS, prior_calls=4),
    "guarded_prompt": _guarded("guarded_prompt"),
    "guarded_all": _guarded("guarded_all"),
    "graph_off": _graph("guarded_off", "graph_off", cost_basis="hand_loop"),
    "graph_all": _graph("guarded_all", "graph_all", cost_basis="guarded_all"),
    "workflow": _workflow(),
    "graph_approve_all": _approval("graph_approve_all", "all_writes"),
    "graph_approve_risk": _approval("graph_approve_risk", "risk_tiered"),
}
DEFAULT_STRATEGY = "single_round"
# Request characters per input token, measured from the recorded t1 bodies in
# tests/fixtures/recorded/ (OpenAI 10,515 chars = 1,834 tokens; Anthropic 10,351 = 3,681,
# which includes its hidden tool prompt). A test keeps these in line with the fixtures.
CHARS_PER_TOKEN = {"openai": 5.7, "anthropic": 2.8}
PRIOR_OUTPUT_TOKENS_PER_CALL = 400   # until a sweep of the model has been measured
WORST_TOOL_RESULT_TOKENS = 600       # what one batch of tool results adds at most
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
    strategy: str = DEFAULT_STRATEGY

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
                         strategy: str = DEFAULT_STRATEGY) -> list[float]:
    costs = []
    for path in sorted(Path(results_dir).glob("*.json")):
        doc = json.loads(path.read_text())
        if doc.get("model") == model and doc.get("strategy") == strategy:
            costs += [t["cost_usd"] for t in doc["trials"] if not t["error"]]
    return costs


def worst_trial_cost(tokens: float, input_price: float, output_price: float,
                     max_calls: int) -> float:
    """Every call at the output limit, nothing cached. Each call after the first carries the
    history so far: one more batch of tool results and one more full output per step."""
    return sum(
        (tokens + (i - 1) * (WORST_TOOL_RESULT_TOKENS + MAX_OUTPUT_TOKENS)) * input_price
        + MAX_OUTPUT_TOKENS * output_price
        for i in range(1, max_calls + 1)
    ) / 1e6


def estimate(tasks: list[Task], model: str, trials_per_task: int,
             results_dir: Path = RESULTS_DIR, strategy: str = DEFAULT_STRATEGY) -> Estimate:
    plan = STRATEGIES[strategy]
    provider = model_entry(model)["provider"]
    price = price_for(model)
    tokens = statistics.mean(request_chars(model, t.ticket) / CHARS_PER_TOKEN[provider]
                             for t in tasks)
    input_price = max(price.input, price.cache_write or 0.0)   # no cache discount assumed
    worst = worst_trial_cost(tokens, input_price, price.output, plan.max_calls)
    if plan.max_usd is not None:
        # The budget is checked before each call, so a run can pass it by one call, then
        # make the reply-only call and at most one truncation retry: three calls at the
        # largest history.
        last_call = (worst_trial_cost(tokens, input_price, price.output, plan.max_calls)
                     - worst_trial_cost(tokens, input_price, price.output, plan.max_calls - 1))
        worst = min(worst, plan.max_usd + 3 * last_call)
    measured = measured_trial_costs(model, results_dir, strategy)
    borrowed = (measured_trial_costs(model, results_dir, plan.cost_basis)
                if not measured and plan.cost_basis else [])
    if measured:
        expected = statistics.mean(measured)
        basis = f"measured: mean of {len(measured)} earlier {strategy} trials of {model}"
    elif borrowed:
        expected = statistics.mean(borrowed)
        basis = (f"borrowed: mean of {len(borrowed)} earlier {plan.cost_basis} trials of "
                 f"{model} (same loop; none of {strategy} measured yet)")
    else:
        expected = plan.prior_calls * (tokens * input_price
                                       + PRIOR_OUTPUT_TOKENS_PER_CALL * price.output) / 1e6
        basis = (f"prior: {plan.prior_calls} calls, {round(tokens)} input tokens per call from "
                 f"the request size, {PRIOR_OUTPUT_TOKENS_PER_CALL} output tokens per call, "
                 "no cache")
    return Estimate(model, len(tasks) * trials_per_task, round(tokens), expected, worst, basis,
                    strategy)


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

_BASELINES: dict[str, dict] = {}


def _baseline(task: Task) -> dict:
    """The store before the run: seeded, plus the task's setup. Deterministic, so cached."""
    key = json.dumps(task.setup, sort_keys=True)
    if key not in _BASELINES:
        conn = trial_store(task, faults=False)
        _BASELINES[key] = snapshot(conn)
        conn.close()
    return _BASELINES[key]


def approvals_of(events: list[dict]) -> dict:
    """The approval pauses of a trial: counts, and each packet with its decisions, so the
    report can replay the packets through other reviewers without re-running anything."""
    reviews, decided = [], {e["call_id"]: e for e in events if e["type"] == "approval_decision"}
    for request in (e for e in events if e["type"] == "approval_request"):
        reviews.append({"packet": request["packet"],
                        "decisions": {c["call_id"]: {k: decided.get(c["call_id"], {}).get(k)
                                                     for k in ("decision", "reviewer", "reason")}
                                      for c in request["calls"]}})
    verdicts = [d["decision"] for r in reviews for d in r["decisions"].values()]
    return {"requests": len(reviews), "flagged_calls": len(verdicts),
            "approved": verdicts.count("approve"), "rejected": verdicts.count("reject"),
            "reviews": reviews}


def run_trial(task: Task, trial: int, *, adapter, sweep_id: str, runs_dir: Path,
              langfuse=None, strategy: str = DEFAULT_STRATEGY) -> dict:
    """One attempt at one task. API failures become an error trial; Ctrl-C propagates."""
    run_id = f"{sweep_id}-{task.id}-k{trial}"
    tracer = Tracer(run_id, log_dir=Path(runs_dir) / sweep_id, langfuse=langfuse, phase=PHASE)
    plan = STRATEGIES[strategy]
    conn = trial_store(task, invariants=plan.invariants)
    error = None
    try:
        plan.run(task.ticket.strip(), ticket_id=task.id, conn=conn, adapter=adapter,
                 tracer=tracer)
    except Exception as exc:  # noqa: BLE001 -- an API or harness failure, not a wrong answer
        error = f"{type(exc).__name__}: {exc}"
    finally:
        faults = env_of(conn).faults
        tracer.event("end_state", db_diff=diff(_baseline(task), snapshot(conn)),
                     **({"faults_fired": faults.fired} if faults else {}))
        conn.close()
    events = read_events(tracer.path)
    if any(e["type"] == "run_start" for e in events):
        transcript = Transcript.from_events(events)
    else:  # failed before the run started, so only the end state was logged
        transcript = Transcript(task.id, task.ticket, adapter.model, strategy,
                                db_diff=events[-1]["db_diff"])
    if error and not transcript.error:
        transcript = replace(transcript, error=error)
    verdict = grade(task, transcript)
    attack = grade_attack(task, transcript)
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
        "attack": attack.to_dict() if attack else None,
        "safety": safety(task, transcript).to_dict(),
        "approvals": approvals_of(events),
        "transcript": transcript.to_dict(),
    }


# --- Sweep ---------------------------------------------------------------------------

def new_sweep_id(model: str, trials: int, strategy: str = DEFAULT_STRATEGY) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{strategy}-{model}-k{trials}"


def run_sweep(tasks: list[Task], *, adapter, trials_per_task: int, cap_usd: float,
              est: Estimate, task_set: str = DEFAULT_SET, results_dir: Path = RESULTS_DIR,
              runs_dir: Path = EVAL_RUNS_DIR, langfuse=None, sweep_id: str | None = None,
              progress=lambda record, spent: None, strategy: str = DEFAULT_STRATEGY) -> dict:
    """Run every task `trials_per_task` times, task-major, and record the results.

    Before each trial, if what has been spent plus that trial's worst case would cross
    `cap_usd`, the sweep halts. Spend is read from the model calls actually logged, so a
    trial that crashed after one call still counts.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Known: {', '.join(STRATEGIES)}")
    sweep_id = sweep_id or new_sweep_id(adapter.model, trials_per_task, strategy)
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
                               langfuse=mirror, strategy=strategy)
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
            "strategy": strategy,
            "max_model_calls": STRATEGIES[strategy].max_calls,
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
            "strategy": strategy, "model": adapter.model, "task_set": task_set,
            "tasks": len(tasks), "trials_per_task": trials_per_task,
            "trials_planned": len(plan), "trials_run": len(records),
            "est_usd": f"{est.expected_usd:.6f}", "worst_usd": f"{est.worst_usd:.6f}",
            "cap_usd": f"{cap_usd:.4f}", "spent_usd": f"{spent:.6f}", "status": status,
            "results_file": results_file.name, "git_commit": commit,
        }, results_dir)
    return doc
