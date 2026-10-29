"""LangChain's create_agent with our tools, driven by the fake chat model. No API calls.

It is not evaluated; these tests pin down what the write-up says about it.
"""

import sqlite3

import pytest
from langchain_core.messages import HumanMessage

from arl.env.seed import new_store
from arl.framework.models import ChatSetup
from arl.framework.prebuilt_agent import build_prebuilt_agent, thread_shared_store
from fake_chat import FakeToolChatModel
from scripted import calls, reply
from test_guarded_loop import LOOK, NOTE, REFUND, refunds

LAMP = ("get_order", {"order_id": "ORD-1003"})
CANCEL = ("cancel_order", {"order_id": "ORD-1003", "reason": "Ordered the wrong desk lamp"})


def agent(*steps, conn):
    fake = FakeToolChatModel(steps=list(steps))
    return build_prebuilt_agent(ChatSetup(fake, "openai", "gpt-6-luna"), conn), fake


def ask(graph, text="Please help."):
    return graph.invoke({"messages": [HumanMessage(text)]})


def test_it_runs_the_same_tools(tmp_path):
    conn = thread_shared_store()
    graph, _ = agent(calls(LAMP), calls(CANCEL), reply("Cancelled."), conn=conn)
    final = ask(graph)
    assert final["messages"][-1].text == "Cancelled."
    assert conn.execute("SELECT status FROM orders WHERE id='ORD-1003'").fetchone()[0] == "cancelled"


def test_its_tools_run_in_another_thread():
    graph, _ = agent(calls(LAMP), reply("x"), conn=new_store())
    with pytest.raises(sqlite3.ProgrammingError, match="same thread"):
        ask(graph)


def test_the_call_limit_ends_with_a_canned_message_not_a_reply():
    steps = [calls(("get_order", {"order_id": f"ORD-{2000 + n}"})) for n in range(12)]
    graph, fake = agent(*steps, conn=thread_shared_store())
    final = ask(graph)
    assert len(fake.calls) == 10                       # the cap held
    assert final["messages"][-1].text == "Model call limits exceeded: run limit (10/10)"
    # Our loops spend the 10th call on a reply with tools off, so the customer gets one.


def _with_note(conn):
    from arl.env.seed import apply_setup
    apply_setup(conn, NOTE)
    return conn


def test_taint_middleware_blocks_a_later_write():
    conn = _with_note(thread_shared_store())
    graph, _ = agent(calls(LOOK), calls(REFUND), reply("A colleague will help."), conn=conn)
    final = ask(graph)
    assert final["tainted"] is True and refunds(conn) == 0


def test_taint_middleware_misses_a_write_in_the_same_batch():
    # ToolNode runs a batch concurrently from one state snapshot, so the note read by the
    # first call cannot block the second. The guarded loop and the graph agent run calls in
    # order and do block it (test_graph_agent, the twin "taint, same batch").
    conn = _with_note(thread_shared_store())
    graph, _ = agent(calls(LOOK, REFUND), reply("Refunded."), conn=conn)
    ask(graph)
    assert refunds(conn) == 1
