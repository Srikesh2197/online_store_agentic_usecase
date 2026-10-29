"""Multi-agent patterns (Stage 8, ladder rung 4), built directly on LangGraph.

    specialists.py   who the agents are: their tools and prompts
    supervisor.py    orchestrator-workers: the graph agent whose tools include agents
    handoffs.py      peers taking turns on one shared conversation

Both keep a single writer, and both run through the same harness as every other strategy.
"""

# The supervisor's limits, here (no imports) so the runner can size a trial's worst case
# without loading the framework.
SUB_MAX_STEPS = 5          # a specialist's own model calls, its report included
MAX_DELEGATIONS = 8        # specialist runs per ticket
