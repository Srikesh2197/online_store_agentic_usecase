"""Threads (Stage 7): runs that outlive the process that started them.

A thread is one run of the graph agent with everything it needs on disk:

    runs/threads/checkpoints.sqlite     LangGraph's checkpoints, every thread (SqliteSaver)
    runs/threads/threads.sqlite         the registry: ticket, model, strategy, status, pid,
                                        working time so far, Langfuse ids, a cancel flag
    runs/threads/<thread>/store.db      the thread's own copy of the store
    runs/threads/<thread>/keys.db       its idempotency keys, ATTACHed as schema `keys`, so
                                        a write and its key are committed together
    runs/threads/<thread>/<thread>.jsonl  the trace: one file across every pause and process

A checkpoint saves the graph state only. The store and the keys are files so that a run
killed after a write can be resumed against the store as it is, and its re-run write is
recognised by its key. Nothing here notices a dead process: a person resumes it
(`arl resume`), which is the gap between a checkpoint and durable execution.
"""

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from langgraph.runtime import RunControl

from arl.env.store import EnvConfig, connect, env_of
from arl.evals.dbdiff import diff, snapshot
from arl.foundations.hand_loop import MAX_STEPS
from arl.foundations.single_round import RunResult
from arl.framework.approval import ALL_WRITES, RISK_TIERED
from arl.framework.graph_agent import (
    AgentContext,
    compiled_graph,
    drive,
    log_decisions,
    resume_with,
    run_config,
    run_graph_agent,
)
from arl.guardrails import ALL, OFF
from arl.tracing.tracer import RUNS_DIR, Tracer, read_events

THREADS_DIR = RUNS_DIR / "threads"
PHASE = "phase-7"
KEYS_SCHEMA = "keys"
# Strategies a thread can run: the guards, and the approval policy (None: no gate).
THREAD_STRATEGIES = {
    "graph_off": (OFF, None),
    "graph_all": (ALL, None),
    "graph_approve_all": (ALL, ALL_WRITES),
    "graph_approve_risk": (ALL, RISK_TIERED),
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- The store and the keys, as files -------------------------------------------------------

def attach_keys(conn: sqlite3.Connection, folder: Path) -> None:
    conn.execute(f"ATTACH DATABASE ? AS {KEYS_SCHEMA}", (str(folder / "keys.db"),))


def create_store(folder: Path, source: sqlite3.Connection) -> sqlite3.Connection:
    """Copy a seeded (and set-up) in-memory store into `folder/store.db`, with its keys in
    `folder/keys.db`. The environment travels with it, keys now in the attached file."""
    folder.mkdir(parents=True, exist_ok=True)
    conn = connect(str(folder / "store.db"))
    source.backup(conn)
    attach_keys(conn, folder)
    conn.env = replace(env_of(source), key_schema=KEYS_SCHEMA)
    return conn


def open_store(folder: Path, env: EnvConfig) -> sqlite3.Connection:
    """Reopen a thread's store in a new process. Fault injectors are not saved, so a resumed
    segment runs without them."""
    conn = connect(str(folder / "store.db"))
    attach_keys(conn, folder)
    conn.env = replace(env, key_schema=KEYS_SCHEMA, faults=None)
    return conn


@lru_cache(maxsize=32)
def checkpointer(path: str):
    """A SqliteSaver on `path`, one per file per process. Its connection may be used from
    another thread (the saver locks it), as LangGraph's documentation shows."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


# --- The registry -----------------------------------------------------------------------------

FIELDS = ("thread_id", "ticket_id", "ticket", "task_id", "model", "strategy", "status", "pid",
          "created_at", "updated_at", "elapsed_s", "sender_customer_id", "invariants",
          "trace_context", "baseline", "cancel_requested", "reply")


class Registry:
    def __init__(self, root: Path = THREADS_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "threads.sqlite"
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS threads (thread_id TEXT PRIMARY KEY, ticket_id TEXT, "
                "ticket TEXT, task_id TEXT, model TEXT, strategy TEXT, status TEXT, pid INTEGER, "
                "created_at TEXT, updated_at TEXT, elapsed_s REAL DEFAULT 0, "
                "sender_customer_id TEXT, invariants INTEGER, trace_context TEXT, baseline TEXT, "
                "cancel_requested TEXT, reply TEXT)")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, **fields) -> None:
        fields = {"created_at": _now(), "updated_at": _now(), **fields}
        with self._conn() as conn:
            conn.execute(f"INSERT INTO threads ({', '.join(fields)}) VALUES "
                         f"({', '.join('?' * len(fields))})", list(fields.values()))

    def update(self, thread_id: str, **fields) -> None:
        fields["updated_at"] = _now()
        with self._conn() as conn:
            conn.execute(f"UPDATE threads SET {', '.join(f'{k} = ?' for k in fields)} "
                         "WHERE thread_id = ?", [*fields.values(), thread_id])

    def get(self, thread_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM threads WHERE thread_id = ?",
                               (thread_id,)).fetchone()
        if row is None:
            raise KeyError(f"No thread '{thread_id}' in {self.path}.")
        record = dict(row)
        record["status"] = status_of(record)
        return record

    def all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM threads ORDER BY created_at").fetchall()
        return [{**dict(r), "status": status_of(dict(r))} for r in rows]


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def status_of(record: dict) -> str:
    """`running` in the registry but its process is gone means the process died mid-run."""
    if record["status"] == "running" and not _alive(record.get("pid")):
        return "crashed"
    return record["status"]


class CancelWatcher:
    """Watches the registry's cancel flag from a background thread and asks the run to drain:
    LangGraph stops it at the next step boundary, with its checkpoint saved."""

    def __init__(self, registry: Registry, thread_id: str, interval: float = 0.2):
        self.registry, self.thread_id, self.interval = registry, thread_id, interval
        self.control = RunControl()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                who = self.registry.get(self.thread_id).get("cancel_requested")
            except (KeyError, sqlite3.Error):
                continue
            if who:
                self.control.request_drain(f"cancelled by {who}")
                return

    def __enter__(self) -> RunControl:
        self._thread.start()
        return self.control

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


# --- Starting, continuing and cancelling a thread ---------------------------------------------

@dataclass(frozen=True)
class Thread:
    thread_id: str
    folder: Path
    trace: Path


def thread_paths(thread_id: str, root: Path = THREADS_DIR) -> Thread:
    folder = Path(root) / thread_id
    return Thread(thread_id, folder, folder / f"{thread_id}.jsonl")


def _status(result: RunResult) -> str:
    return result.status if result.status in ("paused", "cancelled") else "done"


def _finish(registry: Registry, tracer: Tracer, store, thread: Thread, result: RunResult,
            baseline: dict) -> None:
    status = _status(result)
    if status == "done":   # as the eval runner does: the end state, for graders and audit
        tracer.event("end_state", db_diff=diff(baseline, snapshot(store)))
    # The first segment's Langfuse ids are kept: every later segment joins that run span.
    first = registry.get(thread.thread_id)["trace_context"] is None and tracer.trace_context()
    registry.update(thread.thread_id, status=status, pid=None,
                    elapsed_s=round(result.latency_ms / 1000, 3), reply=result.reply,
                    cancel_requested=None,
                    **({"trace_context": json.dumps(tracer.trace_context())} if first else {}))


def start_thread(ticket: str, *, ticket_id: str, source_store, chat, strategy: str,
                 thread_id: str, task_id: str | None = None, root: Path = THREADS_DIR,
                 reviewer=None, echo=lambda title, payload: None, langfuse=None,
                 sleep=time.sleep) -> RunResult:
    """Start a run as a thread: copy the store to files, register it, run until it ends,
    pauses for approval, or is cancelled."""
    guards, policy = THREAD_STRATEGIES[strategy]
    registry = Registry(root)
    thread = thread_paths(thread_id, root)
    store = create_store(thread.folder, source_store)
    baseline = snapshot(store)
    env = env_of(store)
    registry.add(thread_id=thread_id, ticket_id=ticket_id, ticket=ticket, task_id=task_id,
                 model=chat.model, strategy=strategy, status="running", pid=os.getpid(),
                 sender_customer_id=env.sender_customer_id, invariants=int(env.invariants),
                 baseline=json.dumps(baseline))
    tracer = Tracer(thread_id, log_dir=thread.folder, langfuse=langfuse, phase=PHASE)
    with CancelWatcher(registry, thread_id) as control:
        result = run_graph_agent(ticket, ticket_id=ticket_id, conn=store, adapter=None,
                                 tracer=tracer, echo=echo, guards=guards, strategy=strategy,
                                 chat=chat, policy=policy, reviewer=reviewer,
                                 checkpointer=checkpointer(str(Path(root) / "checkpoints.sqlite")),
                                 control=control, sleep=sleep)
    _finish(registry, tracer, store, thread, result, baseline)
    store.close()
    return result


def pending_packet(thread_id: str, *, root: Path = THREADS_DIR) -> dict | None:
    """The review packet a paused thread is waiting on, from its checkpoint."""
    record = Registry(root).get(thread_id)
    _, policy = THREAD_STRATEGIES[record["strategy"]]
    graph = compiled_graph(policy, checkpointer(str(Path(root) / "checkpoints.sqlite")))
    interrupts = graph.get_state({"configurable": {"thread_id": thread_id}}).interrupts
    return interrupts[0].value if interrupts else None


def continue_thread(thread_id: str, *, chat, decisions: dict | None = None,
                    root: Path = THREADS_DIR, reviewer=None, how: str = "resume",
                    echo=lambda title, payload: None, langfuse=None,
                    sleep=time.sleep) -> RunResult:
    """Continue a thread in this process: with `decisions` (approve or reject) for a paused
    thread, or from its last checkpoint for a crashed or cancelled one.

    The run's working time so far is restored, so the time budget does not count the time
    the thread spent waiting for a person or for someone to resume it."""
    registry = Registry(root)
    record = registry.get(thread_id)
    guards, policy = THREAD_STRATEGIES[record["strategy"]]
    thread = thread_paths(thread_id, root)
    store = open_store(thread.folder, EnvConfig(invariants=bool(record["invariants"]),
                                                sender_customer_id=record["sender_customer_id"]))
    graph = compiled_graph(policy, checkpointer(str(Path(root) / "checkpoints.sqlite")))
    tracer = Tracer(thread_id, log_dir=thread.folder, langfuse=langfuse, phase=PHASE)
    clock = time.perf_counter
    ctx = AgentContext(setup=chat, conn=store, tracer=tracer, guards=guards,
                       max_steps=MAX_STEPS, echo=echo, clock=clock, sleep=sleep,
                       started=clock() - (record["elapsed_s"] or 0.0))
    registry.update(thread_id, status="running", pid=os.getpid(), cancel_requested=None)
    trace_context = json.loads(record["trace_context"]) if record["trace_context"] else None
    segment = {"thread_id": thread_id, "how": how, "trace_context": trace_context}
    with CancelWatcher(registry, thread_id) as control, \
            tracer.run(ticket_id=record["ticket_id"], ticket=record["ticket"],
                       model=record["model"], provider=chat.provider,
                       strategy=record["strategy"], resume=segment):
        config = run_config(tracer, MAX_STEPS, gated=policy is not None, thread_id=thread_id)
        run_input = None
        if decisions is not None:
            packet = graph.get_state(config).interrupts[0].value
            log_decisions(tracer, packet, decisions)
            run_input = resume_with(decisions)
        result = drive(graph, run_input, config, ctx, reviewer=reviewer, control=control)
    _finish(registry, tracer, store, thread, result, json.loads(record["baseline"]))
    store.close()
    return result


def cancel_thread(thread_id: str, *, who: str, root: Path = THREADS_DIR) -> str:
    """Cancel a thread. A running one is asked to drain (its own process stops it at the next
    step boundary); one that is paused or crashed is marked cancelled here. Either way its
    checkpoints stay, so its state can be read, and it can still be resumed."""
    registry = Registry(root)
    record = registry.get(thread_id)
    if record["status"] == "running":
        registry.update(thread_id, cancel_requested=who)
        return "requested"
    if record["status"] in ("done", "cancelled"):
        return record["status"]
    thread = thread_paths(thread_id, root)
    tracer = Tracer(thread_id, log_dir=thread.folder, phase=PHASE)
    tracer.continue_log()
    tracer.event("run_cancelled", reason=f"cancelled by {who}", thread_id=thread_id,
                 was=record["status"])
    registry.update(thread_id, status="cancelled", pid=None)
    return "cancelled"


def thread_state(thread_id: str, *, root: Path = THREADS_DIR) -> dict:
    """The thread's last checkpoint: its state values, the next node, and its history."""
    record = Registry(root).get(thread_id)
    _, policy = THREAD_STRATEGIES[record["strategy"]]
    graph = compiled_graph(policy, checkpointer(str(Path(root) / "checkpoints.sqlite")))
    config = {"configurable": {"thread_id": thread_id}}
    snap = graph.get_state(config)
    return {"values": snap.values, "next": snap.next,
            "history": [(s.metadata.get("step"), s.metadata.get("source"), s.next)
                        for s in graph.get_state_history(config)]}


# --- The audit trail --------------------------------------------------------------------------

WRITE_KINDS = ("write", "escalate")


def reconstruct(events: list[dict]) -> dict:
    """A run rebuilt from its JSONL trace alone: who asked for what, who approved what, what
    was committed, and how it ended, across every segment of the run."""
    from arl.env.tools import _BY_NAME

    start = next(e for e in events if e["type"] == "run_start")
    out = {"run_id": start["run_id"], "ticket_id": start["ticket_id"], "ticket": start["ticket"],
           "model": start["model"], "strategy": start["strategy"], "segments": [],
           "timeline": [], "approvals": [], "committed": [], "reply": None, "status": None}
    committed_ids = set()
    for e in events:
        kind = e["type"]
        if kind in ("run_start", "run_resume"):
            out["segments"].append({"type": kind, "ts": e["ts"], "how": e.get("how")})
        elif kind == "model_response":
            out["timeline"].append(f"model call {e['call_index']}: {e['stop']}")
        elif kind == "tool_call":
            replayed = isinstance(e["result"], dict) and e["result"].get("replayed")
            out["timeline"].append(
                f"{e['name']}({e['arguments']}) -> "
                f"{'error ' + e['result']['error'] if e['is_error'] else 'ok'}"
                f"{' (replayed: already done)' if replayed else ''}")
            tool = _BY_NAME.get(e["name"])
            if (tool and tool.kind in WRITE_KINDS and not e["is_error"]
                    and e["call_id"] not in committed_ids):
                committed_ids.add(e["call_id"])
                out["committed"].append({"call_id": e["call_id"], "tool": e["name"],
                                         "arguments": e["arguments"], "result": e["result"],
                                         "ts": e["ts"]})
        elif kind == "approval_request":
            out["timeline"].append("approval requested for "
                                   + ", ".join(f"{c['tool']} [{c['call_id']}]"
                                               for c in e["calls"]))
        elif kind == "approval_decision":
            out["approvals"].append({k: e.get(k) for k in ("call_id", "tool", "arguments",
                                                           "decision", "reviewer", "reason",
                                                           "ts")})
            out["timeline"].append(f"{e['reviewer']} {e['decision']}d {e['tool']} "
                                   f"[{e['call_id']}]: {e['reason']}")
        elif kind in ("run_paused", "run_cancelled"):
            out["timeline"].append(f"{kind.removeprefix('run_')}: "
                                   f"{e.get('reason')}")
            out["status"] = kind.removeprefix("run_")
        elif kind == "run_end":
            out["reply"], out["status"] = e["reply"], e["status"]
    return out


def render_audit(audit: dict) -> str:
    lines = [f"Run {audit['run_id']}  ({audit['strategy']}, {audit['model']})",
             f"Ticket {audit['ticket_id']}:", *("  " + l for l in audit["ticket"].splitlines()),
             "", "Segments: " + ", ".join(f"{s['type']} at {s['ts']}" for s in audit["segments"]),
             "", "Timeline:", *(f"  {n}. {line}" for n, line in enumerate(audit["timeline"], 1)),
             "", "Approvals:"]
    lines += [f"  {a['ts']}  {a['reviewer']}: {a['decision']} {a['tool']} "
              f"{json.dumps(a['arguments'])} ({a['reason']})" for a in audit["approvals"]] or [
        "  none"]
    lines += ["", "Committed changes:"]
    lines += [f"  {c['tool']}({c['arguments']})" for c in audit["committed"]] or ["  none"]
    lines += ["", f"Status: {audit['status']}", f"Reply: {audit['reply'] or '(none yet)'}"]
    return "\n".join(lines)


def replay_committed(audit: dict, conn) -> None:
    """Apply the run's committed changes, in order, to a fresh store. If the audit trail is
    complete, the result equals the thread's store."""
    from arl.env.tools import execute_tool

    for change in audit["committed"]:
        execute_tool(conn, change["tool"], change["arguments"])


def audit_thread(thread_id: str, *, root: Path = THREADS_DIR) -> dict:
    return reconstruct(read_events(thread_paths(thread_id, root).trace))
