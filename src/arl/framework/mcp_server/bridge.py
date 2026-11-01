"""The client side of the MCP store: a bridge from an MCP server to the graph agent's tools.

    with served_store(conn, workdir, tracer=tracer) as tools:
        run_graph_agent(..., agent_fields={"store_specs": tools.specs(),
                                           "run_tool": tools.run_tool})

What the graph gets from the server: the tool definitions the model is offered (`specs`), and
an executor with execute_tool's signature (`run_tool`). Everything else stays in the graph's
`tools` node as in every strategy: the toolset guard, loop detection, taint, grounding,
retries and the idempotency keys, all decided with our own registry's tool kinds, never with
the server's annotations.

The pin. Tool names, descriptions and schemas become part of the model's prompt, and the
server writes them. So every definition is hashed and compared with pins.json each time the
tools are listed. A changed, missing or extra tool fails closed: `mcp_pin_mismatch` is
logged and PinMismatch raised before any model call. The list is fetched once per run, past
the client's cache, and `listChanged` is ignored, so a definition that changes mid-run (a
"rug pull") never reaches the model. A pin covers the definitions, not what the server does
when called: a server we did not write would need its results treated as untrusted.

The store. The trial's store is an in-memory database in this process, which a server in
another process cannot open. So it is handed over as a file: backed up into `store.db`, opened
by the server, and copied back into the trial's connection when the run ends. The runner then
reads the end state from the same connection as always, so the graders are unchanged. Over
stdio the server gets the environment from a JSON file; faults are refused there (their
counts live here). In-process (tests) the server shares this process's environment, faults
included.

The SDK's client is async; the graph is not. A blocking portal (anyio) runs the client's
event loop in a thread, and each call waits for its answer.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from mcp import Client, StdioServerParameters

from arl.env.faults import raise_fault
from arl.env.store import env_of
from arl.framework.mcp_server.server import (
    META_KEY,
    SERVER_NAME,
    build_server,
    open_store,
    tool_definitions,
)
from arl.llm.types import ToolSpec

PINS_PATH = Path(__file__).with_name("pins.json")


# --- The pin ---------------------------------------------------------------------------------

def definition_hash(tool) -> str:
    """A hash of everything about a tool that reaches the model or the client's decisions."""
    annotations = (tool.annotations.model_dump(mode="json", by_alias=True, exclude_none=True)
                   if tool.annotations else None)
    canonical = json.dumps({"name": tool.name, "description": tool.description,
                            "inputSchema": tool.input_schema, "annotations": annotations},
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def pin_of(tools) -> dict:
    hashes = {tool.name: definition_hash(tool) for tool in tools}
    joined = "\n".join(f"{name}:{h}" for name, h in sorted(hashes.items()))
    return {"set": hashlib.sha256(joined.encode()).hexdigest()[:16], "tools": hashes}


def load_pins(path: Path = PINS_PATH) -> dict:
    return json.loads(Path(path).read_text())


def pin_problems(tools, pinned: dict | None) -> list[dict]:
    """How the listed tools differ from the pin. An empty list means they match."""
    if not pinned:
        return [{"problem": "no_pin", "server": SERVER_NAME}]
    got = pin_of(tools)["tools"]
    want = pinned["tools"]
    problems = [{"problem": "changed", "tool": n, "expected": want[n], "got": got[n]}
                for n in sorted(want.keys() & got.keys()) if want[n] != got[n]]
    problems += [{"problem": "missing", "tool": n} for n in sorted(want.keys() - got.keys())]
    problems += [{"problem": "unpinned", "tool": n} for n in sorted(got.keys() - want.keys())]
    return problems


class PinMismatch(RuntimeError):
    """The server's tool definitions are not the pinned ones: the server is not used."""


# --- The tools --------------------------------------------------------------------------------

class McpTools:
    def __init__(self, portal, client, *, tracer=None, pins: dict | None = None,
                 check_pin: bool = True):
        self._portal, self._client, self._tracer = portal, client, tracer
        self._pins = pins if pins is not None else load_pins()
        self._check_pin = check_pin
        self.calls = 0

    def _list(self) -> list:
        tools, cursor = [], None
        while True:   # paginated; past the client's cache, so a changed definition is seen
            page = self._portal.call(partial(self._client.list_tools, cursor=cursor,
                                             cache_mode="bypass"))
            tools += page.tools
            cursor = page.next_cursor
            if not cursor:
                return tools

    def specs(self) -> tuple[ToolSpec, ...]:
        tools = self._list()
        if self._check_pin:
            problems = pin_problems(tools, self._pins.get(SERVER_NAME))
            if problems:
                if self._tracer:
                    self._tracer.event("mcp_pin_mismatch", server=SERVER_NAME,
                                       problems=problems)
                raise PinMismatch(f"{SERVER_NAME}: the tool definitions do not match the pin "
                                  f"({', '.join(p['problem'] + ':' + p.get('tool', '') for p in problems)})")
        return tuple(ToolSpec(t.name, t.description or "", t.input_schema) for t in tools)

    def run_tool(self, conn, name: str, arguments: str, *,
                 idempotency_key: str | None = None) -> dict:
        """execute_tool's signature. `conn` is ignored: the server holds the store."""
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as exc:   # as execute_tool says it; MCP sends objects only
            return {"error": "invalid_arguments",
                    "message": f"The arguments are not valid JSON: {exc.msg}."}
        if not isinstance(args, dict):
            return {"error": "invalid_arguments",
                    "message": "The arguments must be a JSON object. Nothing was changed."}
        meta = {META_KEY: idempotency_key} if idempotency_key else None
        self.calls += 1
        result = self._portal.call(partial(self._client.call_tool, name, args, meta=meta))
        payload = (result.structured_content if isinstance(result.structured_content, dict)
                   else json.loads(result.content[0].text))
        if result.is_error and payload.get("error") == "tool_fault":
            raise_fault(payload["fault"], name)
        return payload


# --- The store, served ------------------------------------------------------------------------

def _single(group: BaseExceptionGroup) -> BaseException:
    """The one exception inside nested single-exception groups, or the group itself."""
    while isinstance(group, BaseExceptionGroup) and len(group.exceptions) == 1:
        group = group.exceptions[0]
    return group


@contextmanager
def served_store(conn: sqlite3.Connection, workdir: Path, *, transport: str = "stdio",
                 tracer=None, check_pin: bool = True, pins: dict | None = None,
                 definitions=None):
    """Serve the trial's store over MCP for one run; copy it back when the run ends."""
    env = env_of(conn)
    if transport == "stdio" and env.faults is not None:
        raise NotImplementedError("Faults are not served over stdio.")
    if env.key_schema != "temp":
        raise NotImplementedError("Only per-run (TEMP) idempotency keys are served over MCP.")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "store.db"
    with sqlite3.connect(path) as file:
        conn.backup(file)
    file.close()
    started = time.perf_counter()
    server = None
    if transport == "stdio":
        env_path = workdir / "env.json"
        env_path.write_text(json.dumps({"invariants": env.invariants,
                                        "sender_customer_id": env.sender_customer_id}))
        target = StdioServerParameters(command=sys.executable, args=[
            "-m", "arl.framework.mcp_server", "--store", str(path), "--env", str(env_path)])
    elif transport == "memory":
        server = build_server(lambda: open_store(str(path), env),
                              **({"definitions": definitions} if definitions else {}))
        target = server
    else:
        raise ValueError(f"Unknown transport '{transport}'.")
    try:
        try:
            with start_blocking_portal() as portal, \
                    portal.wrap_async_context_manager(Client(target)) as client:
                tools = McpTools(portal, client, tracer=tracer, pins=pins, check_pin=check_pin)
                tools.connect_ms = round((time.perf_counter() - started) * 1000)
                yield tools
        except BaseExceptionGroup as group:   # the client's task group wraps what we raised
            raise _single(group) from None
        if server is not None:
            server.close_store()
        with sqlite3.connect(path) as file:   # the server's writes, back into the trial's store
            file.backup(conn)
        file.close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_graph_mcp(ticket: str, *, conn, tracer, transport: str = "stdio",
                  check_pin: bool = True, pins: dict | None = None, definitions=None,
                  **kwargs):
    """Run one ticket through the graph agent with its store tools served over MCP. Takes
    run_graph_agent's arguments."""
    from arl.framework.graph_agent import run_graph_agent

    workdir = tracer.path.parent / f"{tracer.run_id}.mcp"
    with served_store(conn, workdir, transport=transport, tracer=tracer, check_pin=check_pin,
                      pins=pins, definitions=definitions) as tools:
        started = time.perf_counter()
        specs = tools.specs()
        tracer.event("mcp_connect", server=SERVER_NAME, transport=transport,
                     connect_ms=tools.connect_ms,
                     list_ms=round((time.perf_counter() - started) * 1000),
                     tools=len(specs), pin="checked" if check_pin else "off")
        fields = {**kwargs.pop("agent_fields", {}), "store_specs": specs,
                  "run_tool": tools.run_tool}
        return run_graph_agent(ticket, conn=conn, tracer=tracer, agent_fields=fields,
                               **kwargs)


__all__ = ["McpTools", "PinMismatch", "definition_hash", "load_pins", "pin_of", "pin_problems",
           "run_graph_mcp", "served_store", "tool_definitions"]
