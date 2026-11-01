"""An MCP server for the store tools, with execute_tool behind it.

The high-level MCPServer builds each tool's schema from Python type hints. Our tools already
have strict JSON schemas (the ones every strategy sends), so the low-level Server is used and
`tools/list` returns exactly tool_specs(): the same names, descriptions and schemas, plus
annotations (hints a client must not trust from a server it does not control).

`tools/call` runs execute_tool on the server's own connection to the store, so schema
validation, the invariants, the signed-in sender, injected faults and idempotency keys apply
as in every other strategy. The key travels in the request's `_meta` (META_KEY): it is the
harness's concern, not an argument the model sees. A fault comes back as an error result
`{"error": "tool_fault", "fault": kind}`, which the client turns back into the exception, so
its retries work unchanged.

Handlers run on the event loop's thread, which is not the thread that made the server, so
the connection is opened on first use, there, and calls are handled one at a time.
"""

import json
import sqlite3
from collections.abc import Callable

from mcp import types
from mcp.server import Server

from arl.env.faults import ToolFault
from arl.env.store import EnvConfig, Store
from arl.env.tools import TOOLS, execute_tool, tool_specs

SERVER_NAME = "arl-store"
META_KEY = "arl/idempotency_key"


def tool_definitions() -> list[types.Tool]:
    kinds = {tool.name: tool.kind for tool in TOOLS}
    return [types.Tool(name=spec.name, description=spec.description,
                       input_schema=spec.parameters,
                       annotations=types.ToolAnnotations(read_only_hint=kinds[spec.name] == "read"))
            for spec in tool_specs()]


def open_store(path: str, env: EnvConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(path, factory=Store, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.env = env
    return conn


def _result(payload: dict, *, is_error: bool) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                structured_content=payload, is_error=is_error)


def build_server(connect: Callable[[], sqlite3.Connection], *,
                 definitions: Callable[[], list[types.Tool]] = tool_definitions) -> Server:
    """The server. `connect` opens the store on first use; `definitions` is what
    `tools/list` returns (a test passes a poisoned one)."""
    held: list[sqlite3.Connection] = []

    def conn() -> sqlite3.Connection:
        if not held:
            held.append(connect())
        return held[0]

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=definitions())

    async def call_tool(ctx, params) -> types.CallToolResult:
        key = (params.meta or {}).get(META_KEY)
        try:
            result = execute_tool(conn(), params.name, json.dumps(params.arguments or {}),
                                  idempotency_key=key)
        except ToolFault as exc:
            return _result({"error": "tool_fault", "fault": exc.kind, "message": str(exc)},
                           is_error=True)
        return _result(result, is_error="error" in result)

    server = Server(SERVER_NAME, on_list_tools=list_tools, on_call_tool=call_tool)
    server.close_store = lambda: [c.close() for c in held]
    return server
