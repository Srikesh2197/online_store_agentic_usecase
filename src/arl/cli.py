"""The `arl` command line."""

import json
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv

from arl import ROOT

TICKETS_DIR = ROOT / "tickets"

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Agent Reliability Lab."""
    load_dotenv(ROOT / ".env")


# OpenAI's encrypted reasoning, and the signature on Anthropic's thinking blocks.
_BLOB_KEYS = ("encrypted_content", "signature")


def _shorten_blobs(value):
    """For display only: cut encrypted reasoning blobs down. The log keeps them whole."""
    if isinstance(value, dict):
        return {
            k: f"{v[:40]}... ({len(v)} chars, full value in the log)"
            if k in _BLOB_KEYS and isinstance(v, str) and len(v) > 80
            else _shorten_blobs(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_shorten_blobs(v) for v in value]
    return value


def _echo(title: str, payload: object) -> None:
    typer.secho(f"\n===== {title} =====", bold=True)
    typer.echo(json.dumps(_shorten_blobs(payload), indent=2))


STRATEGY_HELP = ("single_round (rung 1), hand_loop (rung 2), or rung 2 with guardrails: "
                 "guarded_prompt (prompt-only defence) or guarded_all (every guardrail).")


def _strategy(name: str):
    from arl.evals.runner import STRATEGIES

    if name not in STRATEGIES:
        raise typer.BadParameter(f"Unknown strategy '{name}'. Known: {', '.join(STRATEGIES)}",
                                 param_hint="--strategy")
    return STRATEGIES[name]


def _load_ticket(ticket: str) -> tuple[str, str]:
    path = Path(ticket) if ticket.endswith(".yaml") else TICKETS_DIR / f"{ticket}.yaml"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in TICKETS_DIR.glob("*.yaml")))
        raise typer.BadParameter(f"No ticket file {path}. Known tickets: {known}")
    data = yaml.safe_load(path.read_text())
    return data["id"], data["text"].strip()


@app.command()
def run(
    ticket: str = typer.Option(..., "--ticket", "-t", help="Ticket id (e.g. t1) or a YAML path."),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Model id; its provider comes from config/models.yaml. Default: `default` there.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Do not print raw requests/responses."),
    strategy: str = typer.Option("single_round", "--strategy", "-s", help=STRATEGY_HELP),
) -> None:
    """Run one ticket through a strategy and print what went over the wire."""
    from arl.env.seed import new_store
    from arl.env.store import EnvConfig
    from arl.llm import make_adapter
    from arl.llm.pricing import load_models
    from arl.tracing.tracer import Tracer, langfuse_client, new_run_id

    plan = _strategy(strategy)
    conn = new_store()
    conn.env = EnvConfig(invariants=plan.invariants)
    ticket_id, text = _load_ticket(ticket)
    adapter = make_adapter(model or load_models()["default"])
    tracer = Tracer(new_run_id(ticket_id), langfuse=langfuse_client())

    result = plan.run(
        text,
        ticket_id=ticket_id,
        conn=conn,
        adapter=adapter,
        tracer=tracer,
        echo=(lambda title, payload: None) if quiet else _echo,
    )

    typer.secho("\n===== REPLY =====", bold=True)
    typer.echo(result.reply or "(no reply text)")
    typer.secho("\n===== SUMMARY =====", bold=True)
    u = result.usage
    typer.echo(
        f"strategy: {plan.name}   status: {result.status}   stop: {result.stop}   "
        f"model: {adapter.model} ({adapter.provider})\n"
        f"model calls: {result.model_calls}   tool calls: {result.tool_calls}\n"
        f"tokens: {u.input_tokens} in ({u.cached_input_tokens} cache read, "
        f"{u.cache_write_tokens} cache write), "
        f"{u.output_tokens} out ({u.reasoning_tokens} reasoning)\n"
        f"cost: ${result.cost_usd:.6f}   latency: {result.latency_ms} ms\n"
        f"log: {tracer.path.relative_to(ROOT)}\n"
        f"langfuse: {tracer.trace_url or 'not configured'}"
    )


@app.command("eval")
def eval_(
    model: str = typer.Option(None, "--model", "-m",
                              help="Model id. Default: `default` in config/models.yaml."),
    trials: int = typer.Option(5, "--trials", "-k", min=1, help="Trials per task."),
    tasks: str = typer.Option("all", "--tasks",
                              help="all, a category (read/write/refuse/escalate), or ids: c01,c07"),
    task_set: str = typer.Option("capability", "--task-set",
                                 help="capability (v1) or adversarial (Stage 5)."),
    cap: float = typer.Option(0.50, "--cap", help="Hard cost cap for this sweep, in US dollars."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the estimate and stop."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask before spending."),
    langfuse: bool = typer.Option(False, "--langfuse",
                                  help="Mirror up to 30 trials of this sweep to Langfuse."),
    strategy: str = typer.Option("single_round", "--strategy", "-s", help=STRATEGY_HELP),
) -> None:
    """Run the task set through a strategy, k trials per task, under a cost cap."""
    from arl.evals import report, runner
    from arl.evals.tasks import load_tasks, select
    from arl.llm.pricing import load_models

    plan = _strategy(strategy)
    model = model or load_models()["default"]
    try:
        chosen = select(load_tasks(task_set), tasks)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--task-set") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--tasks") from exc
    est = runner.estimate(chosen, model, trials, strategy=plan.name)
    spent = runner.phase_spent()
    worst_basis = (f"the ${plan.max_usd:.4f} per-run budget plus 3 calls past it"
                   if plan.max_usd else
                   f"{plan.max_calls} calls, every one at max_tokens, no cache")
    typer.secho("===== ESTIMATE =====", bold=True)
    typer.echo(
        f"sweep:     {plan.name} · {model} · {task_set} · {len(chosen)} tasks × {trials} trials "
        f"= {est.trials} trials\n"
        f"expected:  ${est.expected_usd:.4f}  (${est.per_trial_expected:.6f} per trial; "
        f"{est.basis})\n"
        f"worst:     ${est.worst_usd:.4f}  (${est.per_trial_worst:.6f} per trial: "
        f"{worst_basis})\n"
        f"cap:       ${cap:.4f}  (the sweep halts before any trial whose worst case would "
        f"cross it)\n"
        f"{runner.PHASE} spent so far: ${spent:.4f} of about ${runner.PHASE_BUDGET_USD:.2f}"
    )
    if est.worst_usd > cap:
        typer.secho("note: the worst case is above the cap, so the cap may halt this sweep.",
                    fg="yellow")
    if dry_run:
        return
    if not yes:
        typer.confirm("Run this sweep?", abort=True)

    from arl.llm import make_adapter
    from arl.tracing.tracer import langfuse_client

    def progress(record: dict, total: float) -> None:
        result = {True: "pass", False: "FAIL", None: "ERROR"}[record["success"]]
        failed = [c["name"] for c in record["verdict"]["checks"] if not c["passed"]]
        attack = record.get("attack")
        if attack:
            failed.insert(0, "HARM" if attack["harmed"] else
                          "attempted" if attack["attempted"] else "resisted")
        typer.echo(f"{record['task_id']:<30} k{record['trial']}  {result:<5} "
                   f"${record['cost_usd']:.6f}  {(record['latency_ms'] or 0) / 1000:5.1f}s  "
                   f"total ${total:.4f}  {', '.join(failed)}"
                   + (f"  [{record['error']}]" if record["error"] else ""))

    doc = runner.run_sweep(chosen, adapter=make_adapter(model), trials_per_task=trials,
                           cap_usd=cap, est=est,
                           langfuse=langfuse_client() if langfuse else None, progress=progress,
                           strategy=plan.name, task_set=task_set)
    typer.secho(f"\n===== {doc['status'].upper()} =====", bold=True)
    typer.echo(report.summary_table([doc]))
    typer.echo(f"\nresults: results/{doc['sweep_id']}.json   spent: ${doc['spent_usd']:.4f}")


@app.command("label")
def label_(
    build_pool: bool = typer.Option(False, "--build-pool",
                                    help="Sample the items to label from the Phase 2-3 results."),
    top_up: int = typer.Option(0, "--top-up", min=0,
                               help="Add this many more items from the failure strata."),
    split: bool = typer.Option(False, "--split",
                               help="Split the labelled items into examples / tuning / test."),
) -> None:
    """Label replies pass or fail, with a one-line critique. Resumable: q quits, nothing is lost."""
    from collections import Counter

    from arl.evals import labels as lab
    from arl.evals.report import load_results

    pool = lab.read_pool()
    if build_pool or top_up:
        docs = [load_results(p, regrade=True) for p in sorted(lab.ROOT.glob("results/2026*.json"))
                if not p.name.endswith(".judge.json")]
        candidates = lab.candidates(docs)
        if build_pool:
            if pool:
                raise typer.BadParameter(f"{lab.POOL_FILE} already exists; it is frozen.")
            items = lab.number(lab.sample(candidates))
            lab.write_pool(items)
        else:
            share = top_up // len(lab.FAIL_STRATA)
            targets = {s: share + (n < top_up % len(lab.FAIL_STRATA))
                       for n, s in enumerate(lab.FAIL_STRATA)}
            items = lab.number(lab.sample(candidates, targets, seed=lab.SEED + 1, exclude=pool),
                               start=len(pool) + 1)
            lab.write_pool(items, append=True)
        strata = ", ".join(f"{s} {n}" for s, n in sorted(Counter(i.stratum for i in items).items()))
        typer.echo(f"Wrote {len(items)} items to {lab.POOL_FILE.relative_to(lab.ROOT)} ({strata}).")
        return
    if not pool:
        raise typer.BadParameter("No pool yet. Run `arl label --build-pool` first.")
    if split:
        result = lab.make_split(pool, lab.read_labels())
        lab.write_split(result)
        typer.echo(f"Split with seed {result['seed']}: "
                   + ", ".join(f"{s} {len(result[s])} items / {len(result['tasks'][s])} tasks"
                               for s in ("examples", "tuning", "test"))
                   + f"\nWritten to {lab.SPLIT_FILE.relative_to(lab.ROOT)}.")
        return
    lab.label_loop(pool, lab.LABELS_FILE, ask=typer.prompt, echo=typer.echo)


def _judge_send():
    from anthropic import Anthropic

    from arl.llm.anthropic_adapter import anthropic_sender

    return anthropic_sender(Anthropic())


def _judge_estimate(est, cap: float) -> None:
    typer.secho("===== JUDGE ESTIMATE =====", bold=True)
    typer.echo(
        f"calls:     {est.calls}  (shared prompt about {est.prefix_tokens} tokens, cached; "
        f"case about {est.case_tokens} tokens)\n"
        f"expected:  ${est.expected_usd:.4f}  (${est.per_call_expected:.6f} per call)\n"
        f"worst:     ${est.worst_usd:.4f}  (${est.per_call_worst:.6f} per call: no cache, "
        f"every call at max_tokens)\n"
        f"cap:       ${cap:.4f}  (halts before any call whose worst case would cross it)")


@app.command("judge-validate")
def judge_validate(
    split_name: str = typer.Option(..., "--split", help="tuning or test (test is scored once)."),
    note: str = typer.Option("", "--note", help="What changed in the prompt (tuning log)."),
    cap: float = typer.Option(0.10, "--cap", help="Hard cost cap, in US dollars."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the estimate and stop."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask before spending."),
    force: bool = typer.Option(False, "--force", help="Score the test split again (recorded)."),
    limit: int = typer.Option(0, "--limit", min=0, help="Only the first N items (a smoke test)."),
) -> None:
    """Score the judge against your labels on one split: confusion matrix, rates, intervals."""
    import json as _json

    from arl.evals import judge_validation as jv
    from arl.evals import labels as lab
    from arl.evals.graders import judge as jg

    if split_name not in ("tuning", "test"):
        raise typer.BadParameter("tuning or test", param_hint="--split")
    pool, labels, split = lab.read_pool(), lab.read_labels(), lab.read_split()
    by_id = {i.item_id: i for i in pool}
    items = [by_id[i] for i in split[split_name]][: limit or None]
    lock = lab.LABELS_DIR / "test.lock"
    if split_name == "test" and lock.exists() and not force and not dry_run:
        raise typer.BadParameter(f"The test split was already scored ({lock.read_text().strip()}). "
                                 "It is scored once; --force re-scores and is recorded.")
    run_id = f"{jg._stamp()}-judge-{split_name}"
    judge = jg.Judge(_judge_send() if not dry_run else None,
                     jg.examples_from_split(pool, labels, split),
                     tracer=None if dry_run else jg.make_tracer(run_id))
    est = jg.estimate(judge, items)
    typer.echo(f"split: {split_name}, {len(items)} items · prompt {judge.prompt_hash} "
               f"({jg.PROMPT_VERSION}) · model {judge.model}")
    _judge_estimate(est, cap)
    if dry_run:
        return
    if not yes:
        typer.confirm("Run the judge?", abort=True)

    def progress(item, verdict, spent):
        human = labels[item.item_id].label
        mark = "ERROR" if verdict.error else ("agree" if verdict.verdict == human else "DISAGREE")
        typer.echo(f"{item.item_id} {item.task_id[:3]}  human {human:<4} judge "
                   f"{verdict.verdict or '-':<4} {mark:<8} ${spent:.4f}  {verdict.critique[:90]}")

    verdicts, status, spent = jg.judge_batch(judge, items, cap, est.per_call_worst, progress)
    human = [labels[i.item_id].label for i in items[: len(verdicts)]]
    validation = jv.validate(human, [v.verdict for v in verdicts])
    out = lab.LABELS_DIR / f"{run_id}.json"
    out.write_text(_json.dumps({
        "run_id": run_id, "split": split_name, "prompt_version": jg.PROMPT_VERSION,
        "prompt_hash": judge.prompt_hash, "model": judge.model, "status": status,
        "spent_usd": spent, "forced": force, "note": note,
        "validation": validation.to_dict(),
        "items": [{"item_id": i.item_id, "task_id": i.task_id, "human": labels[i.item_id].label,
                   "human_critique": labels[i.item_id].critique, **v.to_dict()}
                  for i, v in zip(items, verdicts, strict=False)],
    }, indent=1) + "\n")
    text = jv.report(validation, f"{split_name} · prompt {judge.prompt_hash}")
    typer.echo("\n" + text)
    if split_name == "tuning":
        log = lab.LABELS_DIR / "tuning-log.md"
        if not log.exists():
            log.write_text("# Judge tuning log\n\n| Run | Prompt | TPR | TNR | Kappa | Errors | "
                           "$ | What changed |\n|---|---|---|---|---|---|---|---|\n")
        c = validation.confusion
        with log.open("a") as f:
            f.write(f"| {run_id} | {judge.prompt_hash} | {jv._fmt(c.tpr)} | {jv._fmt(c.tnr)} | "
                    f"{jv._fmt(c.kappa)} | {validation.judge_errors} | {spent:.4f} | {note} |\n")
    else:
        lock.write_text(f"{run_id} prompt {judge.prompt_hash}" + (" (forced)" if force else "")
                        + "\n")
        (lab.LABELS_DIR / "validation-v1.json").write_text(_json.dumps({
            "run_id": run_id, "prompt_hash": judge.prompt_hash, "model": judge.model,
            "forced": force, **validation.to_dict()}, indent=1) + "\n")
        (lab.LABELS_DIR / "validation-v1.md").write_text(
            f"# Judge validation, held-out set\n\nRun `{run_id}`, judge `{judge.model}`, "
            f"prompt `{judge.prompt_hash}` ({jg.PROMPT_VERSION}), {len(verdicts)} items, "
            f"${spent:.4f}." + (" **Re-scored with --force.**" if force else "")
            + "\n\n" + text)
    jg._ledger(run_id, "labels", len(verdicts), est, cap, spent, status, out.name, judge.model)
    typer.echo(f"results: {out.relative_to(lab.ROOT)}   spent: ${spent:.4f}   status: {status}")


@app.command("judge")
def judge_(
    results: Path = typer.Argument(..., help="A results file from `arl eval`."),  # noqa: B008
    cap: float = typer.Option(0.20, "--cap", help="Hard cost cap, in US dollars."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the estimate and stop."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask before spending."),
) -> None:
    """Add the advisory judge column to a sweep: writes <results>.judge.json beside it."""
    import json as _json

    from arl.evals import labels as lab
    from arl.evals.graders import judge as jg
    from arl.evals.report import load_results
    from arl.evals.transcript import Transcript

    doc = load_results(results)
    trials = [t for t in doc["trials"] if t["success"] is not None]
    items = [jg.item_from_transcript(Transcript.from_dict(t["transcript"]),
                                     f"{t['task_id']}#k{t['trial']}") for t in trials]
    pool, labels, split = lab.read_pool(), lab.read_labels(), lab.read_split()
    run_id = f"{jg._stamp()}-judge-{doc['sweep_id']}"
    judge = jg.Judge(_judge_send() if not dry_run else None,
                     jg.examples_from_split(pool, labels, split),
                     tracer=None if dry_run else jg.make_tracer(run_id))
    validation_file = lab.LABELS_DIR / "validation-v1.json"
    validation = _json.loads(validation_file.read_text()) if validation_file.exists() else None
    if validation and validation["prompt_hash"] != judge.prompt_hash:
        typer.secho(f"warning: prompt {judge.prompt_hash} is not the validated prompt "
                    f"{validation['prompt_hash']}; the corrected rate will not be shown.",
                    fg="yellow")
    est = jg.estimate(judge, items)
    typer.echo(f"sweep: {doc['sweep_id']}, {len(items)} trials · prompt {judge.prompt_hash}")
    _judge_estimate(est, cap)
    if dry_run:
        return
    if not yes:
        typer.confirm("Run the judge?", abort=True)
    verdicts, status, spent = jg.judge_batch(
        judge, items, cap, est.per_call_worst,
        lambda item, v, total: typer.echo(f"{item.item_id:<38} {v.verdict or 'ERROR':<5} "
                                          f"${total:.4f}  {v.critique[:80]}"))
    sidecar = Path(results).with_suffix(".judge.json")
    sidecar.write_text(_json.dumps({
        "run_id": run_id, "sweep_id": doc["sweep_id"], "model": judge.model,
        "prompt_version": jg.PROMPT_VERSION, "prompt_hash": judge.prompt_hash,
        "validation": (validation if validation
                       and validation["prompt_hash"] == judge.prompt_hash else None),
        "status": status, "spent_usd": spent,
        "trials": [{"task_id": t["task_id"], "trial": t["trial"], **v.to_dict()}
                   for t, v in zip(trials, verdicts, strict=False)],
    }, indent=1) + "\n")
    jg._ledger(run_id, doc["task_set"], len(verdicts), est, cap, spent, status, sidecar.name,
               judge.model)
    typer.echo(f"\njudge column: {sidecar}   spent: ${spent:.4f}   status: {status}")


@app.command("report")
def report_(
    results: list[Path] = typer.Argument(..., help="Results files; the first is arm A."),  # noqa: B008
    regrade: bool = typer.Option(False, "--regrade",
                                 help="Grade the stored transcripts again with the current tasks."),
    show: str = typer.Option(None, "--show", help="Print one transcript: a task id or prefix."),
    trial: int = typer.Option(1, "--trial", help="Which trial to show."),
    out: Path = typer.Option(None, "--out", help="Also write the report to this file."),  # noqa: B008
    tasks: str = typer.Option(None, "--tasks",
                              help="Only these task ids or prefixes, comma-separated: c07,c08"),
) -> None:
    """Tables from results files: summary, categories, per-task variance, paired comparison."""
    from arl.evals import report

    docs = [report.load_results(path, regrade=regrade) for path in results]
    if tasks:
        docs = [report.restrict(doc, tasks.split(",")) for doc in docs]
    if show:
        typer.echo(report.show_trial(docs[0], show, trial))
        return
    text = report.full_report(docs)
    typer.echo(text)
    if out:
        out.write_text(text)
