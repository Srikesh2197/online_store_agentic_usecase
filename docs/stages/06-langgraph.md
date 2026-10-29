# Stage 6: Port to LangGraph and add a workflow (rung 3)

Sweeps on 2026-10-29 (UTC), through the unchanged harness:
- capability v1, 30 tasks × 5 on `gpt-6-luna`: the graph agent with every guardrail on (`graph_all`) and the workflow (`workflow`);
- adversarial set, 12 tasks × 5 on `gpt-6-luna`: `graph_all`;
- `claude-haiku-5-5`, `graph_all` on Phase 3's 10 tasks × 1, as the second-provider check.

The reference arms are Stage 5's: `guarded_all` on v1 (30 × 5) and on the adversarial set (12 × 5).

Spend was **$0.107** of the planned $2.50:

| Run | Trials | Spend |
|---|---|---|
| Smoke (3 × `graph_all`, 3 × `workflow`, 1 × Haiku) | 7 | $0.003 |
| `graph_all` v1 | 150 | $0.028 |
| `workflow` v1 | 150 | $0.039 |
| `graph_all` adversarial | 60 | $0.027 |
| `graph_all` Haiku | 10 | $0.010 |

To regenerate the tables:

```
arl report --regrade results/20261028T213732Z-guarded_all-gpt-6-luna-k5.json \
  results/20261029T001125Z-graph_all-gpt-6-luna-k5.json \
  results/20261029T002324Z-workflow-gpt-6-luna-k5.json
arl report --regrade results/20261029T001125Z-graph_all-gpt-6-luna-k5.json \
  results/20261029T002324Z-workflow-gpt-6-luna-k5.json
arl report --regrade results/20261028T190807Z-guarded_all-gpt-6-luna-k5.json \
  results/20261029T003444Z-graph_all-gpt-6-luna-k5.json
arl report --regrade results/20261023T114739Z-hand_loop-claude-haiku-5-5-k1.json \
  results/20261029T004359Z-graph_all-claude-haiku-5-5-k1.json
```

They are saved as `results/report-phase6-v1.md`, `report-phase6-v1-workflow-vs-graph.md`, `report-phase6-adversarial.md` and `report-phase6-haiku.md`.

## The concepts

| Term | Here |
|---|---|
| `StateGraph` | A program written as nodes (functions) joined by edges, over a declared state schema (a `TypedDict`). Each node reads the state and returns a partial update |
| Reducer | How an update to one state key is merged. The default overwrites. `add_messages` appends messages; `operator.add` sums counters; `operator.or_` on a bool means "once true, stays true" |
| Super-step | One round of nodes. Updates are merged when it ends, so a node never sees an update made in the same step |
| Conditional edge | A pure function from the state to the next node's name. It routes; it must not change state |
| `recursion_limit` | The framework's step cap, counted in super-steps. Crossing it raises `GraphRecursionError`. The default has been 1,000 since 1.0.6 |
| Routing | A classifier picks one of several fixed paths |
| Prompt chaining | A task split into fixed model calls, each with a narrow job, with code between them |
| Workflow vs agent | In a workflow, code decides the order of steps; in an agent, the model does |

### What maps to what

| Hand loop (`hand_loop.py`, `guarded_loop.py`) | Graph agent (`framework/graph_agent.py`) | Primitive |
|---|---|---|
| `messages` list | state key `messages` | state + `add_messages` |
| `usage`, `cost`, `model_calls`, `tool_calls` | state keys | state + `operator.add` (usage: a dict sum) |
| `call_model()` | `model` node | node |
| `if response.stop == "tool_calls" and not capped` | `after_model` | conditional edge |
| `[run_tool(c) for c in calls]` | `tools` node, sequential (ours, not `ToolNode`) | node |
| `for step in range(1, max_steps + 1)` | the cycle `tools → limits → model` | edges |
| step cap and `stop_reason()` (budgets, loop stop) | `limits` node: sets `cap_status`, appends the closing instruction | node |
| tools off on the last call | `model` reads `cap_status` and binds `tool_choice` none | state |
| `break` and the exit status | `finish` node, then `END` | node + edge |
| `Taint()` in the closure | `tainted` | state + `operator.or_` |
| `Grounding()` and `end_turn()` | `grounded` ids; the super-step boundary is "an earlier turn" | state + union reducer |
| `LoopDetector()` | `call_counts`, `loop_stop` | state + count-merge, `or_` |
| retries, idempotency key `run id : call id` | inside `tools`, the key from `AIMessage.tool_calls[i]["id"]` | inside a node |
| truncation retry | inside `model` | inside a node |
| prompt defence | the system message | prompt |
| invariants, idempotency storage, faults, notes | unchanged, in `env/` | tool-side |
| our adapter builds the request body | LangChain builds it (`init_chat_model`, `bind_tools`) | model layer |
| (none) | `recursion_limit = 4 × max_steps + 5`, a backstop that never fired | framework |

```mermaid
graph TD;
  __start__ --> model;
  model -.->|tool_calls, not capped| tools;
  model -.->|anything else| finish;
  tools --> limits;
  limits --> model;
  finish --> __end__;
```

The Stage 5 guardrail modules are objects that keep their own state. In the graph, a node rebuilds each one from the state, uses it, and writes its changes back as an update. That is clunkier than the loop, and it is the point: the state is data the framework merges, can draw, and (in Stage 7) can save.

### The workflow

```mermaid
graph TD;
  __start__ --> route;
  route -.->|policy_question| reply;
  route -.->|any other intent| gather;
  gather -.->|email only| pick;
  gather -.->|status| reply;
  gather -.->|cancel, address_change, refund_return| decide;
  gather -.->|complaint, other_request, unclear| escalate;
  pick -.-> decide;
  pick -.-> escalate;
  pick -.-> reply;
  decide -.->|a write on a tainted run| escalate;
  decide -.->|a call| act;
  decide -.->|no call| reply;
  act --> reply;
  escalate --> reply;
  reply --> __end__;
```

- **route** (model, structured output): one of 8 intents, the order ids, the email, a one-line summary.
- **gather** (code): `get_order` for each id given, and `get_shipment` unless the intent is cancel or address change. With only an email: `find_customer`, `list_orders`, then **pick** (model) chooses the order.
- **decide** (model): only that intent's tools are bound (cancel → `cancel_order`, `escalate_to_human`; address → `update_shipping_address`, `escalate_to_human`; refund or return → `issue_refund`, `create_return`, `escalate_to_human`). One round. No call means a refusal or an answer.
- **act** (code): runs the decided calls, through grounding (only an order a lookup returned), retries and idempotency keys from the decide call's ids. The invariants are in the tools.
- **escalate** (code): "escalate otherwise". `complaint` → `complaint`, `other_request` → `policy_exception`, `unclear` → `cannot_verify`; and any write decided on a tainted run (the Rule of Two as an edge).
- **reply** (model): no tools bound.

At most 4 model calls (5 with a truncation retry), so there is no loop to cap or detect.

## Options and what we chose

| Decision | Options | Chosen | Why |
|---|---|---|---|
| Model layer | LangChain chat models; our `llm/` adapters inside a node | LangChain (`init_chat_model`, with `model_provider` and options from `models.yaml`) | The framework's model layer is what this stage is about, and `create_agent` and the workflow need it. Our usage and stop mapping is reapplied to LangChain's messages, so cost and branching are computed exactly as before (tested on the same bodies) |
| Parity | Byte-identical requests; identical decisions | Decisions: tool calls (turn, name, arguments as sent), results, stops, usage, cost, exits, guard events, idempotency keys, tools-off calls, output limits, end state | LangChain builds its own bodies, so bytes cannot match. Decisions are what the graders and the store see |
| How one script drives both | A message-level fake only; the scripted HTTP bodies into the real chat models | Both: `tests/wire.py` serves `ScriptedModel` through a fake transport to the real `ChatOpenAI` and `ChatAnthropic` (parity and twins); `tests/fake_chat.py` is a fake chat model with `bind_tools` (workflow, `create_agent`, one graph check) | The wire fake tests LangChain's own request building and parsing, which is where the traps were. LangChain's fakes cannot bind tools |
| Tools node | `ToolNode`; our own | Our own, sequential | `ToolNode` runs a batch in a thread pool. Our SQLite connection is thread-bound, and the loop runs calls in order (a note read by the first call blocks a write later in the batch) |
| Where guardrail state lives | Objects in the closure; graph state | Graph state, with reducers | No node or branch can drop taint; Stage 7 can save it |
| Tracing | Our tracer; LangChain callbacks only | Our tracer writes the same JSONL events from the nodes. The Langfuse LangChain callback adds the graph's nodes and generations inside our run span, and our own per-call mirror is switched off for those runs | The graders and `--regrade` work unchanged; Langfuse shows the graph without counting a call twice (checked on a live trace) |
| Classifier | Rules; a model call | A model call with structured output | Free-text tickets; rules would be brittle |
| Taint in the workflow | Block and tell the model; route in code; quarantine the notes | An edge after `decide` routes a tainted write to `escalate` | No loop exists to tell the model. Quarantine (the deciding model never sees the notes) was left as an option |
| Anthropic cache setting | Per call; on the model | `model_kwargs` on the model | It reaches every runnable built on the model, structured output included |
| Graph agent trials | 30 × 3 (plan); 30 × 5 | 30 × 5 | Clean k5 pairing with Stage 5's arms, for about $0.01 more |
| Live arms | Off and on; on only | All on only | "Off" is proven equal to `hand_loop` by the scripted parity tests |

## What the framework gives, and what it hides

**Gives:** the loop as data you can draw; state merging with declared reducers; a backstop on runaway graphs; one message type across providers; provider switching with `init_chat_model`; callbacks (Langfuse saw every node without any code in the nodes); and, from Stage 7, checkpoints and interrupts.

**Hides**, each found and pinned by a test:

| What | Where it showed | Consequence |
|---|---|---|
| `tool_choice="none"` | `ChatAnthropic.bind_tools` reads the string as "force the tool named none", then drops it because thinking is on | The reply-only call at the cap would have had tools on. We pass `{"type": "none"}` |
| The wire body | LangChain sends the OpenAI system prompt as a `system` message inside `input`; our adapter uses `instructions`. It also adds `stream: false` | No decision changed in any scripted case, and live results matched. The audit trail now logs LangChain's view of the request, not the bytes sent |
| Tool concurrency | `ToolNode` (inside `create_agent`) runs a batch in threads | Our store raises `ProgrammingError`; and a note read by one call cannot block a write in the same batch |
| Structured-output parsing | `ChatOpenAI` parses the JSON inside the model call | An unreadable answer raises before its usage is returned, so that call's tokens are missing from our trace. The workflow logs a `structured_output_error` and escalates |
| The cap in `create_agent` | `ModelCallLimitMiddleware(exit_behavior="end")` | The run ends with the canned text "Model call limits exceeded: run limit (10/10)", not a reply to the customer |
| Defaults | `ChatOpenAI` defaults to `store=True` on the Responses API | We pass `store=False`, as the adapter does |

**`create_agent` beside the graph** (`framework/prebuilt_agent.py`, 53 lines of code, not evaluated): the loop, the tools node and the exits come prebuilt; the step cap is `ModelCallLimitMiddleware`; taint is a `wrap_tool_call` middleware whose flag lives in the agent's state with an OR reducer. What you can no longer see or choose: tool concurrency, the reply at the cap, stop-reason handling (truncation and refusal are not told apart), and our trace.

| | Lines of code (no docstrings or comments) |
|---|---|
| `hand_loop.py` (rung 2) | 117 |
| `guarded_loop.py` (rung 2 + guardrails) | 181 |
| `graph_agent.py` (rung 3 + guardrails) | 252, plus 124 in `models.py` shared with the workflow |
| `workflow.py` | 371, about 40 of them prompt text |
| `prebuilt_agent.py` | 53 |

## How it is tested

117 new tests (one skipped: Anthropic cannot send invalid JSON). 578 pass and 2 are skipped in total, with no API calls.
- **Parity** (`test_graph_agent.py`): the six Stage 5 scripts on both providers, `hand_loop` against `graph_off`, compared on every decision listed above; plus a fault with guardrails off, reasoning replay, and the same tools reaching the model.
- **Guardrail twins:** 26 scenarios, 49 runs across the two providers: budgets (off, and tokens, dollars, time), loop detection (off, on), grounding (off, and four on), retries and idempotency (fault off, retries, retry without and with a key, retries running out), taint (off, and four on, including a write in the same batch), invariants (off, on), truncation (off, on), and all on. Each runs through `guarded_loop` and the graph with the same guards; the decisions are compared, and the safety outcome is checked again on the graph run.
- **Model layer** (`test_framework_models.py`): every stop kind on both providers, with every usage field set (cache reads, cache writes, reasoning), parsed by our adapter and by LangChain: same usage, cost, stop, tool calls and text.
- **Workflow** (`test_workflow.py`, 18): each chain graded by the real graders, escalate-otherwise for each intent, the taint route, grounding, idempotency, invariants, the budget, truncation, and an unreadable route.
- **`create_agent`** (`test_prebuilt_agent.py`, 5): it runs our tools; its tools run in another thread; the cap's canned text; taint middleware blocks a later write and misses one in the same batch.
- **Runner:** the three strategies sweep through `run_sweep` with the real graders; estimates and the CLI know them.

## What we measured: the port (graph agent vs guarded loop)

Code-graded only. The judge is unvalidated (Stage 4).

| v1, 30 × 5 | Success | pass^5 | Refuse | Calls/run | Tokens in/run | Cached | $/run | p50 / p95 |
|---|---|---|---|---|---|---|---|---|
| `guarded_all` (Stage 5) | 95% | 90% | 73% | 2.92 | 6,591 | 95% | $0.000192 | 5.3 / 10.6 s |
| `graph_all` | **98%** | **93%** | 90% | 2.90 | 6,532 | 96% | $0.000187 | 4.6 / 8.7 s |

| Adversarial, 12 × 5 | Harm | Attempted | Utility | Unsafe | Double write | Runaway | $/run |
|---|---|---|---|---|---|---|---|
| `guarded_all` (Stage 5) | 0% (0/60) | 7% | 75% | 0% | 0% | 2% (one time limit, machine asleep) | $0.000467 |
| `graph_all` | **0% (0/60)** | 5% | **75%** | 0% | 0% | 0% | $0.000455 |

### Findings

1. **The port changed nothing measurable in behaviour or cost.** On v1, `graph_all` was better on 3 tasks, worse on none, 27 ties; per run it made the same number of calls (2.90 against 2.92), sent 1% fewer input tokens, and cost 3% less. On the adversarial set: 12 ties in harm.
2. **The adversarial set still passes:** 0/60 harm, 0 unsafe actions, 0 double writes, 0 runaways, utility 75% as before. No attack succeeded.
3. **The guardrails fired exactly as in the loop.** On the adversarial set both arms set taint 30 times, blocked 13 writes (a04, a07, a14) and retried 15 faults with keys; on v1 no guardrail fired in either arm.

### Direction

The three tasks that improved (c15, c16, c22) are all refusals (refuse 73% → 90%): p = 0.25. Possible causes are LangChain's placement of the system prompt (a `system` message in `input` instead of `instructions`) or noise; this set cannot separate them.

## What we measured: workflow vs agent

| v1, 30 × 5 | Success | pass^5 | Write | Refuse | Failure-derived | Calls/run | Tokens in/run | Cached | $/run | p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| `graph_all` (agent) | **98%** | **93%** | 100% | 90% | 96% | 2.90 | 6,532 | 96% | **$0.000187** | 4.6 / 8.7 s |
| `workflow` | 93% | 83% | 96% | 70% | 86% | 2.80 | 3,694 | 73% | $0.000263 | 4.5 / 7.1 s |

Read, escalate: 100% in both. Unsafe actions, double writes, runaways: 0 in both.

Paired against the agent: the workflow was worse on 3 tasks (c15 2/5, c21 2/5, c23 3/5), better on none, 27 ties; p = 0.25, a **direction**. A 20-point difference is the smallest this set resolves.

### Findings (cost is measured precisely)

1. **The workflow cost 41% more per run** ($0.000263 against $0.000187), although it sent 43% fewer input tokens. Two causes, from the per-call usage:
   - **Cache misses at the reply step.** It read 30% of its input from the cache and wrote a new cache entry (about 850 tokens, at 1.25× the input price) on most calls; the route step read 99% and the decide step 93%. Both start with the same 1,000-token policy prefix, so the cause is not established here (OpenAI routes cache entries by prefix, and several step prompts share the same first 1,000 tokens).
   - **More output:** 224 tokens per run against 176, from three small jobs instead of one conversation.
2. **The workflow is bounded by construction.** Calls per run were 2 (40 runs), 3 (100) or 4 (10), never more; its p95 latency was 1.6 s lower.

### Directions

- **Refuse, then escalate (8 of the workflow's 10 failures: c15 ×3, c21 ×3, c22 ×2).** The decide step has `escalate_to_human` bound and is told "if the request is outside the rules, escalate"; the model files clear refusals as policy exceptions. The agent did the same twice (c22). The step prompt's wording is a likely cause; it was not re-tuned on the test set.
- **Context lost between steps (c23 ×2).** The decide step reasoned that the 30 days count from delivery on 2026-09-07; the reply step sees only the case file and said "it's not too late" without the date. Passing the decision's reason forward is a design fix.
- **Where the workflow does not lose:** every read, escalation and lookup chain (including the email-only tickets through `pick`) passed 5/5.

## What we measured: the second provider

| Haiku 5.5, 10 tasks × 1 | Success | Calls/run | Tokens in/run | Cached | $/run | p50 / p95 |
|---|---|---|---|---|---|---|
| `hand_loop` (Phase 3) | 10/10 | 2.90 | 11,980 | 62% | $0.000914 | 6.9 / 26.7 s |
| `graph_all` | 10/10 | 2.90 | 12,782 | 62% | $0.000974 | 6.0 / 9.7 s |

The Anthropic path works end to end through LangChain: thinking blocks replayed with their signatures, `tool_result` blocks merged before the text in one user turn, the cache setting sent on every call, and the same cache share as our own adapter. The 7% higher cost is the defence section (the arms also differ in guardrails, not only in implementation). One trial per task: a check, not a comparison.

## When you would choose differently in production

- **No framework** when the loop is short, the providers are few, and you must see and pin the wire. Rung 2 was 117 lines; the graph is 252 plus a 124-line model layer, and every LangChain trap above came from the layer we no longer wrote.
- **LangGraph** when the run must survive a crash, wait for a person, or branch: Stage 7 needs checkpoints and interrupts, which a hand loop would have to rebuild. Keep guardrail state in the graph state from the start.
- **`create_agent`** for a standard tool loop where the defaults fit: thread-safe tools, a canned message at the cap acceptable, no need to tell truncation from refusal.
- **If you use LangChain's chat models, pin their requests.** Record and compare their bodies in tests, as `tests/wire.py` does; the `tool_choice` trap would otherwise have shipped silently.
- **A workflow** when categories are well defined and a wrong action is costly: it cannot run away or chain lookups. Here it lost on judgement tasks and cost more. Before using it: put the step instructions where they do not break the cache prefix (or set a cache key per step), carry the decision's reason to the reply step, and make "refuse" an explicit choice in the decide step instead of leaving the escalate tool as the only action.
- **Parse structured output outside the model call** (or use tool calling for it), so a bad answer does not lose its usage.
- **Taint per field, or a person in the loop:** the workflow's tainted-write edge is the natural place for Stage 7's approval node, which could recover a07 and a14 (0/5 utility in both arms).
- **Set a per-request timeout** on the chat model; the default is still the SDK's 600 s.

## Limits

- One model for the main arms; the Haiku arm is 10 × 1.
- 30 v1 tasks: only differences of about 20 points or more are findings. All success differences here are directions.
- The workflow was written once and not tuned on the test set. A tuned workflow could do better; that would need a held-out split.
- The workflow was run on v1 only. The optional adversarial run was skipped.
- The trace's `model_request` holds LangChain's message view, not the wire body; the wire bodies are only seen in tests.
- `results/*.json` record a `-dirty` git commit, because the Phase 6 code was uncommitted when the sweeps ran.
