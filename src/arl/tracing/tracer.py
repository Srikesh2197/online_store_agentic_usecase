"""One trace per run.

The JSONL file is the audit trail: one line per event, in order, holding the full
request and response bodies. When Langfuse keys are present the same run is mirrored
there as a span tree (run -> model calls and tool calls).
"""

import json
import os
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from arl import ROOT
from arl.llm.types import Usage

RUNS_DIR = ROOT / "runs"
PHASE = "phase-1"


def new_run_id(ticket_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{ticket_id}-{uuid.uuid4().hex[:6]}"


def langfuse_client():
    """A Langfuse client if both keys are set, otherwise None (local logging only)."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    from langfuse import Langfuse

    return Langfuse()


class _Record:
    """Filled in by the caller inside a `model_call` or `tool_call` block."""

    def __init__(self):
        self.fields: dict = {}

    def finish(self, **fields) -> None:
        self.fields = fields


class Tracer:
    def __init__(self, run_id: str, log_dir: Path = RUNS_DIR, langfuse=None, phase: str = PHASE):
        self.run_id = run_id
        self.phase = phase
        self.path = Path(log_dir) / f"{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_url: str | None = None
        self._lf = langfuse
        self._root = None
        self._seq = 0

    def event(self, type: str, **fields) -> None:
        self._seq += 1
        line = {
            "seq": self._seq,
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "type": type,
            **fields,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(line) + "\n")

    @contextmanager
    def run(self, *, ticket_id: str, ticket: str, model: str, provider: str, strategy: str):
        self.event("run_start", ticket_id=ticket_id, ticket=ticket, model=model,
                   provider=provider, strategy=strategy)
        with ExitStack() as stack:
            if self._lf:
                from langfuse import propagate_attributes

                self._root = stack.enter_context(
                    self._lf.start_as_current_observation(
                        name=strategy, as_type="span", input=ticket
                    )
                )
                stack.enter_context(
                    propagate_attributes(
                        trace_name=f"{strategy}:{ticket_id}",
                        tags=[self.phase, strategy, provider, model],
                        metadata={"run_id": self.run_id, "ticket_id": ticket_id,
                                  "provider": provider},
                    )
                )
                self.trace_url = self._lf.get_trace_url()
            try:
                yield self
            except Exception as exc:
                self.event("run_error", error=type(exc).__name__, message=str(exc))
                raise
        if self._lf:
            self._lf.flush()

    def end_run(self, *, status: str, reply: str, stop: str, model_calls: int, tool_calls: int,
                usage: Usage, cost_usd: float, latency_ms: int) -> None:
        self.event(
            "run_end", status=status, reply=reply, stop=stop, model_calls=model_calls,
            tool_calls=tool_calls, usage=asdict(usage), cost_usd=cost_usd, latency_ms=latency_ms,
        )
        if self._root:
            self._root.update(
                output=reply,
                metadata={"status": status, "stop": stop, "model_calls": model_calls,
                          "tool_calls": tool_calls, "cost_usd": cost_usd},
            )

    @contextmanager
    def model_call(self, index: int, request: dict, *, provider: str):
        """Wrap one model request.

        Call `finish(response=, usage=, cost_usd=, request_id=, stop=, provider_stop=)`.
        The request and response are logged as sent and received, whichever provider.
        """
        self.event("model_request", call_index=index, provider=provider, request=request)
        with ExitStack() as stack:
            generation = None
            if self._lf:
                generation = stack.enter_context(
                    self._lf.start_as_current_observation(
                        name=f"model_call_{index}",
                        as_type="generation",
                        model=request["model"],
                        # OpenAI calls the conversation `input`; Anthropic calls it `messages`.
                        input=request.get("input", request.get("messages")),
                        metadata={"provider": provider,
                                  "tool_choice": str(request.get("tool_choice"))},
                    )
                )
            record = _Record()
            start = time.perf_counter()
            yield record
            latency_ms = round((time.perf_counter() - start) * 1000)
            usage: Usage = record.fields["usage"]
            self.event(
                "model_response", call_index=index, provider=provider, latency_ms=latency_ms,
                request_id=record.fields.get("request_id"), stop=record.fields.get("stop"),
                provider_stop=record.fields.get("provider_stop"), usage=asdict(usage),
                cost_usd=record.fields["cost_usd"], response=record.fields["response"],
            )
            if generation:
                response = record.fields["response"]
                generation.update(
                    # OpenAI returns `output` items; Anthropic returns `content` blocks.
                    output=response.get("output", response.get("content")),
                    usage_details={
                        "input": usage.input_tokens,
                        "input_cache_read": usage.cached_input_tokens,
                        "input_cache_write": usage.cache_write_tokens,
                        "output": usage.output_tokens,
                        "output_reasoning": usage.reasoning_tokens,
                        "total": usage.input_tokens + usage.output_tokens,
                    },
                    cost_details={"total": record.fields["cost_usd"]},
                )

    @contextmanager
    def tool_call(self, *, call_id: str, name: str, arguments: str):
        """Wrap one tool execution. Call `finish(result=)`."""
        with ExitStack() as stack:
            observation = None
            if self._lf:
                observation = stack.enter_context(
                    self._lf.start_as_current_observation(
                        name=name, as_type="tool", input=arguments, metadata={"call_id": call_id}
                    )
                )
            record = _Record()
            start = time.perf_counter()
            yield record
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            result = record.fields["result"]
            is_error = "error" in result
            self.event(
                "tool_call", call_id=call_id, name=name, arguments=arguments, result=result,
                is_error=is_error, latency_ms=latency_ms,
            )
            if observation:
                observation.update(output=result, level="WARNING" if is_error else "DEFAULT")


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines()]
