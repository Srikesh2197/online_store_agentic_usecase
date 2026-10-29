"""The same agent from LangChain's `create_agent`: for reading beside graph_agent.py.

Not registered with the runner and not evaluated. It shows what the prebuilt loop gives and
what it takes away:

    gives   the loop, the tools node and the exits, in a few lines; guardrails as middleware
            (here the step cap as ModelCallLimitMiddleware, and taint as a wrap_tool_call hook
            whose flag lives in the agent's state with an OR reducer)
    hides   how calls in one response are run: ToolNode runs them concurrently in a thread
            pool, so the tools need a connection usable from any thread, and a note read by
            one call cannot block a write in the same batch (in our loops it does);
            what happens at the cap: the middleware ends the run with a canned text, where
            our loops spend the last call on a reply with tools off;
            the stop reason: a truncated or refused response is not told apart;
            and the trace: only a LangChain callback sees inside
"""

import json
import sqlite3
from operator import or_
from typing import Annotated, NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from arl.env.seed import new_store
from arl.env.store import Store
from arl.env.tools import TOOLS, execute_tool, strict_parameters
from arl.foundations.hand_loop import MAX_STEPS
from arl.foundations.single_round import build_instructions
from arl.framework.models import ChatSetup
from arl.guardrails.permissions import Taint
from arl.guardrails.prompt import DEFENCE


def thread_shared_store() -> sqlite3.Connection:
    """A copy of new_store() that ToolNode's worker threads may use. Our stores are opened
    for one thread, as SQLite does by default; the loops never needed more."""
    shared = sqlite3.connect(":memory:", factory=Store, check_same_thread=False)
    new_store().backup(shared)
    shared.row_factory = sqlite3.Row
    shared.execute("PRAGMA foreign_keys = ON")
    return shared


def as_langchain_tools(conn) -> list[StructuredTool]:
    """Our ten tools as LangChain tools, with the same strict schemas and descriptions."""
    def make(tool):
        def run(**arguments) -> str:
            return json.dumps(execute_tool(conn, tool.name, json.dumps(arguments)))
        return StructuredTool.from_function(func=run, name=tool.name,
                                            description=tool.description,
                                            args_schema=strict_parameters(tool))
    return [make(tool) for tool in TOOLS]


class TaintState(AgentState):
    tainted: NotRequired[Annotated[bool, or_]]


class TaintGate(AgentMiddleware):
    """Stage 5's taint as middleware: block writes once untrusted text has been read."""
    state_schema = TaintState

    def wrap_tool_call(self, request, handler):
        name, call_id = request.tool_call["name"], request.tool_call["id"]
        taint = Taint()
        taint.tainted = bool(request.state.get("tainted"))
        if blocked := taint.check(name):
            return ToolMessage(json.dumps(blocked), tool_call_id=call_id, status="error")
        message = handler(request)
        if taint.observe(name, json.loads(message.content)):
            return Command(update={"tainted": True, "messages": [message]})
        return message


def build_prebuilt_agent(setup: ChatSetup, conn, *, max_steps: int = MAX_STEPS):
    return create_agent(
        setup.chat,
        tools=as_langchain_tools(conn),
        system_prompt=build_instructions() + DEFENCE,
        middleware=[ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),
                    TaintGate()],
    )
