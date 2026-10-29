"""Sub-project 2 (Stage 6 onward): the agent on LangGraph, and a workflow beside it.

    models.py           LangChain chat models from config/models.yaml, and the reading of
                        their messages back into our neutral terms (usage, stop, tool calls)
    graph_agent.py      rung 3: the Stage 5 guarded loop as a StateGraph
    workflow.py         classify, route, a fixed chain per category, escalate otherwise
    prebuilt_agent.py   LangChain's create_agent, for reading beside the graph (not evaluated)

The tools, the store, the guardrail logic, the tracer and the graders are the ones the
foundations use, so every strategy runs through the same harness.
"""
