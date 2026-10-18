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


def _shorten_blobs(value):
    """For display only: cut encrypted reasoning blobs down. The log keeps them whole."""
    if isinstance(value, dict):
        return {
            k: f"{v[:40]}... ({len(v)} chars, full value in the log)"
            if k == "encrypted_content" and isinstance(v, str) and len(v) > 80
            else _shorten_blobs(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_shorten_blobs(v) for v in value]
    return value


def _echo(title: str, payload: object) -> None:
    typer.secho(f"\n===== {title} =====", bold=True)
    typer.echo(json.dumps(_shorten_blobs(payload), indent=2))


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
    model: str = typer.Option(None, "--model", "-m", help="Model id. Default: config/models.yaml."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Do not print raw requests/responses."),
) -> None:
    """Run one ticket through the single round and print what went over the wire."""
    from openai import OpenAI

    from arl.env.seed import new_store
    from arl.foundations.single_round import openai_sender, run_single_round
    from arl.tracing.cost import load_models
    from arl.tracing.tracer import Tracer, langfuse_client, new_run_id

    ticket_id, text = _load_ticket(ticket)
    model = model or load_models()["default"]
    tracer = Tracer(new_run_id(ticket_id), langfuse=langfuse_client())

    result = run_single_round(
        text,
        ticket_id=ticket_id,
        conn=new_store(),
        send=openai_sender(OpenAI()),
        model=model,
        tracer=tracer,
        echo=(lambda title, payload: None) if quiet else _echo,
    )

    typer.secho("\n===== REPLY =====", bold=True)
    typer.echo(result.reply or "(no reply text)")
    typer.secho("\n===== SUMMARY =====", bold=True)
    u = result.usage
    typer.echo(
        f"status: {result.status}   model: {model}   model calls: {result.model_calls}   "
        f"tool calls: {result.tool_calls}\n"
        f"tokens: {u.input_tokens} in ({u.cached_input_tokens} cached), "
        f"{u.output_tokens} out ({u.reasoning_tokens} reasoning)\n"
        f"cost: ${result.cost_usd:.6f}   latency: {result.latency_ms} ms\n"
        f"log: {tracer.path.relative_to(ROOT)}\n"
        f"langfuse: {tracer.trace_url or 'not configured'}"
    )
