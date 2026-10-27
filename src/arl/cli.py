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


STRATEGY_HELP = "single_round (rung 1) or hand_loop (rung 2)."


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
    from arl.llm import make_adapter
    from arl.llm.pricing import load_models
    from arl.tracing.tracer import Tracer, langfuse_client, new_run_id

    plan = _strategy(strategy)
    ticket_id, text = _load_ticket(ticket)
    adapter = make_adapter(model or load_models()["default"])
    tracer = Tracer(new_run_id(ticket_id), langfuse=langfuse_client())

    result = plan.run(
        text,
        ticket_id=ticket_id,
        conn=new_store(),
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
        chosen = select(load_tasks(), tasks)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--tasks") from exc
    est = runner.estimate(chosen, model, trials, strategy=plan.name)
    spent = runner.phase_spent()
    typer.secho("===== ESTIMATE =====", bold=True)
    typer.echo(
        f"sweep:     {plan.name} · {model} · {len(chosen)} tasks × {trials} trials "
        f"= {est.trials} trials\n"
        f"expected:  ${est.expected_usd:.4f}  (${est.per_trial_expected:.6f} per trial; "
        f"{est.basis})\n"
        f"worst:     ${est.worst_usd:.4f}  (${est.per_trial_worst:.6f} per trial: "
        f"{plan.max_calls} calls, every one at max_tokens, no cache)\n"
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
        typer.echo(f"{record['task_id']:<30} k{record['trial']}  {result:<5} "
                   f"${record['cost_usd']:.6f}  {(record['latency_ms'] or 0) / 1000:5.1f}s  "
                   f"total ${total:.4f}  {', '.join(failed)}"
                   + (f"  [{record['error']}]" if record["error"] else ""))

    doc = runner.run_sweep(chosen, adapter=make_adapter(model), trials_per_task=trials,
                           cap_usd=cap, est=est,
                           langfuse=langfuse_client() if langfuse else None, progress=progress,
                           strategy=plan.name)
    typer.secho(f"\n===== {doc['status'].upper()} =====", bold=True)
    typer.echo(report.summary_table([doc]))
    typer.echo(f"\nresults: results/{doc['sweep_id']}.json   spent: ${doc['spent_usd']:.4f}")


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
