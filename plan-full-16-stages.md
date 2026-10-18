# Agent Reliability Lab: project plan

## Context

You want to learn how agentic AI systems work in practice, with the repository as the byproduct. Success means you can explain when an agent is the right tool, how to design, bound, evaluate and operate one, and what each choice trades off, using numbers from your own runs. Your priorities are bounded behaviour, auditability, evaluation and human oversight.

The folder `/Users/luffy/Desktop/Projects/Agentic_AI` is empty and is not yet a git repository. This plan covers the research findings, scope, structure and a stage-by-stage build order. No code is written until you approve it, and then we build one stage at a time.

## Three things to know before you read on

1. **The timeline is longer than I first suggested.** The scope you asked for is about 160–200 hours, which is 13–16 weeks at 12–13 hours a week, not the 6–8 weeks in my earlier question. The cut list is in "Budget and timeline".
2. **The budget is tight.** Planned API spend is about $47 against your $50. If debugging takes more runs than planned, expect $50–70 unless we cut. The runner enforces a hard cap either way.
3. **Small eval sets limit what can be claimed.** With 50 tasks, only differences of roughly 12 points or more can be told apart from noise. The plan says for each experiment whether its result will be a finding or only a description.

## Decisions already made

| Decision | Choice |
|---|---|
| Use case | Support-operations agent for a simulated online store |
| Packaging | One repository, three sub-projects (foundations, framework, ops) |
| Deployment | AWS Lambda container image, streaming function URL, DynamoDB checkpoints |
| Build order | All agent stages first, ops last, deploying the best-measured variant |
| API budget | About $50 in total |
| Pace | 10–15 hours a week |
| Starting point | You have made chat calls but not written tool calling or a loop |

## What the research found

Sources are listed at the end. Findings that shaped the plan:

1. **Simplest thing first is the consensus.** Anthropic, OpenAI and Microsoft all advise a workflow or a single call before an agent. They disagree on the default starting point (raw API, a full harness, or explicit graphs).
2. **ReAct is now "a model calling tools in a loop".** LangChain deprecated `create_react_agent` in favour of `create_agent` plus middleware. The text-parsed Thought/Action form is legacy.
3. **Multi-agent helps parallel work and hurts sequential work.** A Google/MIT study measured +81% on a parallelisable task and −39% to −70% on sequential ones. Anthropic reports about 15× the tokens of a chat. Cognition's current position is that it works when only one agent writes.
4. **Reflection works with a separate evaluator, not self-critique.** Anthropic found agents "confidently praise" their own work.
5. **Injection detectors alone do not hold.** A joint OpenAI/Anthropic/DeepMind paper broke 12 published defences with adaptive attacks at over 90% success. Durable defences are structural: restrict what the agent can do after it reads untrusted content (Meta's "Rule of Two").
6. **Eval practice has settled.** Start with 20–50 tasks, grade outcomes over paths, run several trials, and report pass^k (the share of tasks that succeed on all k trials). Validate a binary judge against human labels using true-positive and true-negative rates; raw agreement overstates quality.
7. **Tool design matters more than tool count.** Few workflow-level tools, long descriptions that say when not to use them, actionable error messages, and bounded response sizes.
8. **Things that changed recently:**
   - The MCP specification of 28 July 2026 is stateless and not backward compatible. `langchain-mcp-adapters` 0.3.2 still pins the older SDK (`mcp<2`).
   - The OpenAI Assistants API is gone; the Responses API is the default and the newest models require it for tools.
   - Newer Claude models reject forced `tool_choice` and non-default `temperature`, so "temperature 0" is not available for determinism.
   - `langgraph-supervisor` is archived; the supervisor pattern is now built directly with subagents as tools.
   - AWS App Runner closed to new customers on 30 April 2026.
   - LiteLLM shipped two malicious PyPI releases in March 2026.
9. **Tracing backends.** Langfuse is MIT-licensed, built on OpenTelemetry, and works with a hand-written loop and with LangGraph. Its free cloud tier is 50,000 units a month, where every trace, span and score counts as a unit. It was acquired by ClickHouse in January 2026 with no licence change. LangSmith's free tier is 5,000 traces a month and it is closed source.

## Topic tiers

| Tier | Topics | Why here |
|---|---|---|
| **Core (must build)** | Tool calling and tool design · hand-written loop (ReAct) · eval harness (outcome checks, trajectory checks, pass^k, cost, latency) · LLM judge validated on your labels · tracing · step, budget and time limits · loop detection · tool permissions · input and output validation · retries and failure injection · prompt-injection tests · workflow versus agent (routing, prompt chaining) · LangGraph state and checkpointing · human approval and interruption · multi-agent (supervisor as orchestrator-workers, handoffs) · deployment and operation | These are the four ladder rungs plus the reliability mechanics you named. Each produces a measurement |
| **Advanced (after the ladder is complete)** | Plan-and-execute · reflection and evaluator-optimizer · MCP server and client · long-term memory and context management · prompt caching | Each only means something as a measured change against a working core, and each can be cut without breaking the ladder |
| **Awareness only** | See the section near the end | They need infrastructure or a second party this project does not have, or are better understood by comparison than by building |

## Use case and concept coverage

**Candidates considered**

- **A. Support operations.** Reads tickets, looks up orders, applies a written policy, and issues refunds, cancellations and address changes against a local SQLite database.
- **B. Data analyst.** Answers questions over public databases with SQL and Python, using BIRD Mini-Dev (500 question/SQL pairs).
- **C. Research agent.** Answers multi-hop questions over Wikipedia and arXiv.

| Concept | A. Support ops | B. Data analyst | C. Research | Built in stage |
|---|---|---|---|---|
| Multi-step use of real tools | Strong | Strong | Strong | 0, 1, 3 |
| Tracing | Strong | Strong | Strong | 0 onward |
| Objectively checkable outcome | Strong (database end state) | Strong (result match) | Partial (live data drifts) | 2 |
| Trajectory rules worth checking | Strong (verify before write) | Partial | Partial | 2 |
| ReAct tool loop | Strong | Strong | Strong | 3 |
| LLM judge has a real job | Strong (reply quality) | Weak | Strong | 4 |
| Limits, retries, tool failure handling | Strong (injected) | Partial | Strong (real network) | 5 |
| Side effects, so permissions matter | Strong | None | None | 6 |
| Indirect prompt injection | Strong (ticket text, order notes) | Partial | Strong | 6 |
| Workflow versus agent; routing and chaining | Strong (routine versus long-tail tickets) | Partial | Partial | 7 |
| Checkpointing, approval, interruption | Strong | Weak | Partial | 8 |
| Multi-agent: supervisor, handoffs, shared versus isolated state | Partial | Partial | Strong | 9 |
| Plan-and-execute, reflection, evaluator-optimizer | Strong | Strong | Strong | 10 |
| MCP | Strong | Strong | Strong | 11 |
| Long-term memory has a purpose | Strong (customer history) | Partial | Partial | 12 |
| Deployment and operation | Strong | Strong | Strong | 13–15 |
| Deterministic and cheap to re-run | Strong | Strong | Weak | all |
| Ready-made task set | No | Yes | Partial | 2, 4 |

**Why A.** Bounded behaviour, auditability and oversight only have teeth when the agent can change something, and A is the only candidate with write actions. Outcomes are checked by comparing database state, the method tau-bench uses.

**Its two weaknesses, and what the plan does about them:**
- You write the task set yourself. That is a core skill, and stage 4 grows it from failures you observe.
- Multi-agent is not a natural winner on sequential tickets. Stage 9 adds a separate set of 20 parallelisable tickets and a many-tools stress set, so multi-agent gets a fair test.

## Why one repository with three sub-projects

- **The eval set and environment are the spine.** Comparing ladder rungs is only valid if every agent runs through the identical harness on the identical tasks. A shared package in one repository guarantees that.
- **Each sub-project has a distinct dependency footprint**, exposed as install extras, so "what each layer adds" is visible in the dependency list as well as the results.
- **Ops builds no agent.** It imports the agent chosen at the end of sub-project 2 and deploys it.

| Sub-project | Stages | Contains | Installs |
|---|---|---|---|
| 1. Foundations | 0–6 | Rungs 1 and 2, eval harness, judge, guardrails | `openai`, `anthropic`, `pydantic`, `langfuse` |
| 2. Framework | 7–12 | Rung 3 (LangGraph), approval, rung 4 (multi-agent), patterns, MCP, memory | adds `langgraph`, `langchain`, `mcp` |
| 3. Ops | 13–15 | Serving, container, AWS, monitoring, online evals, CI | adds `fastapi`, `boto3`, `langgraph-checkpoint-aws` |

## The shared spine

**Environment.** A SQLite store seeded deterministically: customers, orders, items, shipments, refunds. A written policy document sets the rules (refund window, identity verification, when to escalate). About ten tools: five read, four write, one escalate. Each trial starts from a fresh copy of the database.

**Task format.** One YAML file per task: the ticket, the expected database change, the expected disposition (resolved, refused or escalated), facts the reply must contain, trajectory rules (must call, must not call, ordering), and a provenance tag.

**Task sets**

| Set | Size | Frozen at | Purpose |
|---|---|---|---|
| Capability v1 | 50 tasks: 30 written up front, 20 drawn from observed failures | End of stage 4 | Main comparisons. 15 are held out by stratified random draw |
| Adversarial | About 20 tasks | End of stage 6 | Injection, runaway-loop bait, tool faults, over-limit requests |
| Parallel | 20 bulk-audit tasks | Stage 9 | Gives multi-agent a fair test |

The 30 original tasks and the 20 failure-derived tasks are always reported separately, because the second group was selected to be hard for the early rungs.

**Metrics.** The headline is code-graded success: the database end state and trajectory rules, with no model in the grading. Also reported: pass^k, model calls per run, tokens, dollars per run, and latency (median and 95th percentile). From stage 6: unsafe-action rate and attack success rate. The judge's reply-quality score is a separate column, run on one trial per task at milestones only.

**How comparisons are reported**
- Every comparison is paired by task: wins, losses and ties, with a sign test or paired bootstrap.
- Each write-up states the smallest difference the experiment could detect.
- Breakdowns by category have about eight tasks each. They are shown as descriptions, not claims.
- Cost, latency and step counts are precise at this sample size; success rates are not.

**Models.** The primary model stays in the cheapest tier. Stage 2 picks it by measurement.

| Role | Candidates | Price per million tokens (input / output) |
|---|---|---|
| Primary (nearly all runs) | `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5-mini` | $0.10 / $0.50 to $0.25 / $2.00 |
| Secondary (cross-provider check on 15 tasks) | `claude-haiku-4-5` | $1 / $5 |
| Reference (10 hard tasks, once) | `claude-sonnet-5-5` or `gpt-6.1-sol` | $2 / $10 |
| Judge | A different model family from the agent | Haiku-class |

**Tracing.** Every model call and tool call is written to a local JSONL event log. The graders read it, the write-ups cite it, and it is the audit trail. Interactive runs also go to Langfuse for debugging. Sweeps export at most 30 traces each, to stay inside the free tier.

**Testing with a scripted model.** A fake model that replays a fixed sequence of tool calls drives the unit tests. It makes guardrail tests deterministic and free. It proves that code-enforced rules hold; it cannot measure attack success or recovery behaviour, which come from live runs and are reported as rates.

**Stage write-ups.** Each stage ends with `docs/stages/NN-name.md` in a fixed template: the concept, the options, what we chose, the measured result, and when you would choose differently in production.

## Stages in build order

### Sub-project 1: Foundations (no framework)

#### Stage 0. First tool call (ladder rung 1)

- **Learn:** what a tool call looks like on the wire; who runs the tool; how the schema and description steer the model; what a trace is.
- **Questions you should be able to answer:**
  - What does the model receive and return when it "calls a tool"?
  - Why does the description matter as much as the code?
  - What can a single round of tool use not do?
- **Build:** `env/` with the store, seed and three or four read tools; `foundations/single_round.py` against one provider (one model call, run its tool calls, one final call), with the raw request and response printed; `tracing/` with JSONL events and Langfuse export; CLI `arl run`.
- **Libraries:** `openai`, `pydantic`, `langfuse`, `typer`, `pytest`.
- **Experiment:** none measured yet. Run five tickets by hand and read every request, response and trace.
- **Done when:** you can point to each field of a tool call in the raw output and say what it is for; each run appears in the JSONL log and in Langfuse with tokens and cost; tools have unit tests; write-up committed.
- **Effort and cost:** 8–10 hours, about $0.25.

#### Stage 1. Two providers and the full toolset

- **Learn:** how OpenAI's Responses API and Anthropic's Messages API differ in representing calls, results, stop reasons and parallel calls; what a provider-neutral interface has to hide; designing write tools.
- **Questions:**
  - Which differences are cosmetic and which change how a loop must behave?
  - What should a tool return on bad input?
  - How large may a tool response be?
- **Build:** the same single round against the second provider, written separately first; then `llm/` (neutral message types, two adapters, a price table from config); the remaining tools including the four write tools, with Pydantic argument models and actionable errors.
- **Libraries:** adds `anthropic`.
- **Experiment:** the same five tickets on both providers; compare the traces side by side.
- **Done when:** one config switch moves a ticket between providers; adapters are tested against recorded responses; write-up includes a table of provider differences.
- **Effort and cost:** 8–10 hours, about $0.25.

#### Stage 2. Eval harness and baseline

- **Learn:** the vocabulary (task, trial, grader, transcript, outcome); outcome grading versus trajectory grading; non-determinism and pass^k; paired comparison; why the harness comes before the agent.
- **Questions:**
  - What makes a task unambiguous enough to grade?
  - Why grade the end state instead of the steps, and when is a step rule still justified?
  - How large a difference can I trust at this sample size?
- **Build:** the first 30 tasks; `evals/graders/outcome.py` (database diff, reply facts); `evals/graders/trajectory.py` (must-call, must-not-call, ordering, with strict, unordered, subset and superset matching written by hand); `evals/runner.py` (fresh database per trial, k trials, cost cap, dry-run estimate); `evals/report.py` (paired comparison, bootstrap intervals); a spend ledger.
- **Libraries:** `pytest`, `pyyaml`; statistics written by hand with the standard library.
- **Runs:** single round, 30 tasks × 5 trials on the primary; 30 × 1 on three other cheap models and on Haiku; 30 × 3 for each of two tool-description styles.
- **Experiment:**
  - Baseline for rung 1, with per-task variance across the five trials.
  - Model shakedown: pick the primary and secondary from graded results.
  - Tool descriptions: terse versus detailed, paired by task.
- **Done when:** `arl eval` reproduces the table from a clean checkout; graders are unit-tested with hand-made passing and failing transcripts; you have read 20 transcripts and confirmed the grader verdicts; the cost cap halts a run in a test; later-stage cost estimates are replaced with measured ones; write-up committed.
- **Effort and cost:** 14–18 hours, about $2.

#### Stage 3. Hand-written agent loop (ladder rung 2, the ReAct pattern)

- **Learn:** the loop itself (call, run tools, return results, repeat); message history; stop reasons; parallel tool calls; tool errors as feedback to the model.
- **Questions:**
  - What ends the loop, and what happens on a truncated response, a refusal or malformed arguments?
  - Why must all results of one turn go back together?
  - What does the loop add over one round, in success and in cost?
  - Does a better loop or a better model buy more?
- **Build:** `foundations/hand_loop.py`, roughly 150 lines, working with both providers; stop-reason handling; tool errors returned as error results; a plain step cap as the only safety net for now; the scripted fake model for tests.
- **Libraries:** no additions.
- **Runs:** loop, 30 × 5 on the primary; 15 × 1 on Haiku; 10 × 1 on the reference model.
- **Experiment:** rung 1 versus rung 2, paired by task. This difference should be large enough to resolve.
- **Done when:** the loop passes scripted-model tests covering each stop reason; the comparison table exists; you have read and annotated ten failed traces; write-up committed.
- **Effort and cost:** 10–12 hours, about $4.50.

#### Stage 4. Error analysis and a validated LLM judge

- **Learn:** reading traces and grouping failures into a taxonomy; which failures code can check and which need a judge; binary verdicts with a written critique; validating a judge with true-positive rate, true-negative rate and Cohen's kappa; judge biases.
- **Questions:**
  - Why binary instead of a 1–5 scale?
  - Why is raw agreement misleading?
  - When is a judge trustworthy enough to gate a release?
- **Build:** `arl label` (a thin labelling screen: pass or fail plus a one-line critique on the reply); `evals/graders/judge.py` (rubric, reasoning before verdict, structured output, trimmed input of ticket, reply and tool-result summary); `evals/judge_validation.py` (confusion matrix, rates, kappa, intervals); `docs/failure-taxonomy.md`; 20 more tasks drawn from observed failures; the held-out draw; freeze capability set v1 and the definition of success.
- **Libraries:** `streamlit` for the labelling screen.
- **Runs:** about 560 judge calls; rung 1 and rung 2 re-run on v1 at 50 × 5.
- **Experiment:**
  - You label about 150 replies from stages 2 and 3, aiming for an even pass/fail mix. Split 10 as examples, 40 for tuning, 100 held back.
  - Tune the judge prompt on the tuning set, then score the held-back set once.
  - Compare a cheap judge with a stronger one: agreement against cost.
  - Re-run rungs 1 and 2 on frozen v1 to set the reference baseline.
- **Done when:** the validation report states held-back rates, kappa and their intervals; the judge gates nothing unless both rates reach 90% with a lower bound above 80%, and otherwise stays advisory, as the write-up will say; v1 and its baseline are frozen; write-up committed.
- **Effort and cost:** 14–16 hours including about 4 hours of labelling, about $5.50.

#### Stage 5. Limits and failure handling as tested features

- **Learn:** step, token, dollar and wall-clock limits; loop detection; argument and output validation; retries, backoff and idempotency; failing closed.
- **Questions:**
  - Which guardrail belongs in the prompt, which in the loop, and which inside the tool?
  - What should the agent do when a limit trips?
  - How can a retry cause a double refund?
- **Build:** `guardrails/limits.py`; `guardrails/loopdetect.py` (repeated tool-plus-arguments fingerprint); `guardrails/validation.py` (argument errors fed back to the model; a grounding check on the final reply); `env/faults.py`, a seeded fault injector (timeout, server error, malformed output, failure after commit); retries with backoff; idempotency keys on write tools, derived from the run id and the model's tool-call id.
- **Libraries:** `tenacity`.
- **Runs:** 10 fault and loop tasks × 5 trials, guardrails off and on.
- **Experiment:** runaway runs, double writes and recovery rate, off versus on.
- **Done when:** each guardrail has a scripted-model test that fails without it and passes with it; the live before/after table exists; write-up committed.
- **Effort and cost:** 10–12 hours, about $1.50.

#### Stage 6. Permissions and prompt injection

- **Learn:** read and write permission tiers; direct and indirect prompt injection; why prompt-only defences and detectors are not enough; structural defences; the trade against normal success.
- **Questions:**
  - Where does untrusted content enter my agent?
  - What can the agent still do after reading it?
  - What is my attack success rate before and after, and what did the defences cost?
- **Build:** `guardrails/permissions.py` (tiers, a per-run allowlist, a taint flag set when untrusted content is read, writes blocked or escalated once tainted); marking of untrusted fields in tool output; policy invariants enforced in code inside write tools (a refund cannot exceed the amount paid; the order must belong to the verified customer); the adversarial task set, calibrated so the unguarded attack success rate is at least 40%.
- **Libraries:** no additions.
- **Runs:** adversarial 20 × 5, off and on; about 100 ablation runs; v1 at 50 × 5 with all guardrails on.
- **Experiment:**
  - Each defence off versus on: attack success and unsafe actions. Prompt-only, marking, taint and code invariants are separate arms.
  - All guardrails on versus the stage 4 baseline on v1. A small drop will not be resolvable; the write-up will say so.
- **Done when:** code-enforced invariants hold in every scripted test; the live table shows rates per defence; the write-up lists which attacks still succeed; the adversarial set is frozen.
- **Effort and cost:** 12–14 hours, about $4.

### Sub-project 2: Framework (LangGraph)

**Why LangGraph.** State and control flow are explicit, which serves auditability. Checkpointing and interrupts are first-class, which serves oversight. It has been stable at 1.x since October 2025, is MIT-licensed, works with both providers, and has SQLite, Postgres and DynamoDB checkpoint stores.

**How it relates to LangChain.** LangChain 1.x `create_agent` is a ready-made agent loop built on the LangGraph runtime and extended through middleware. We use LangGraph's `StateGraph` directly so the mechanics stay visible, and build the `create_agent` version once in stage 7 to see what it hides.

**Known criticisms to keep in mind:** conceptual overhead for simple agents, API churn, and the point that a checkpoint is not durable execution (something must still notice the failure and resume).

#### Stage 7. Port to LangGraph and add a workflow (ladder rung 3)

- **Learn:** `StateGraph`, state schemas and reducers, nodes, conditional edges, streaming; what the framework gives and what it hides; routing and prompt chaining; workflow versus agent.
- **Questions:**
  - Which graph primitive does each part of my hand loop map to?
  - What did I get for free, and what can I no longer see?
  - When would I choose no framework, LangGraph, or `create_agent`?
  - What does a fixed workflow cost and gain against the agent?
- **Build:** `framework/graph_agent.py` (the same loop as a graph, reusing the stage 5 and 6 guardrails); `framework/workflow.py` (classify, route, a fixed chain per category, escalate otherwise); `framework/prebuilt_agent.py` (`create_agent` with built-in limit middleware, for comparison only); `init_chat_model` for provider switching; the Langfuse callback; a fake chat model that supports tool binding.
- **Libraries:** `langgraph` 1.2, `langchain` 1.4, `langchain-openai`, `langchain-anthropic`.
- **Runs:** graph agent 50 × 3; workflow 50 × 5; `create_agent` 15 × 3; Haiku 15 × 1.
- **Experiment:**
  - Parity, proven with the scripted model: the hand loop and the graph agent must produce identical tool-call sequences. The live run is a confirmation only.
  - Workflow versus agent on v1, paired: success, cost, latency. By-category results are descriptive.
  - Lines of code and dependency count as the cost of the framework.
- **Done when:** scripted parity passes; the adversarial set still passes; the comparison table exists; the write-up includes a "what maps to what" table and a framework comparison.
- **Effort and cost:** 12–14 hours, about $4.

#### Stage 8. Persistence, human approval and interruption

- **Learn:** checkpointers, threads and durability modes; `interrupt()` and `Command(resume=...)`; the fact that a node re-runs from the top on resume; approve, edit and reject; cancelling a run in flight; audit logs.
- **Questions:**
  - What exactly is saved at a checkpoint?
  - Why does approval require persistence?
  - What re-runs on resume, and why does that make write tools dangerous?
  - How do I decide what needs approval without overloading the reviewer?
- **Build:** SQLite checkpointing with synchronous durability; an approval gate in its own node, placed before the node that runs writes; an approval policy (writes above a threshold, or any write after tainted input); approve, edit and reject paths; cancellation of a running thread with its state kept; an idempotency ledger inside the store; an audit log of who approved what; a thin Streamlit approval inbox; a scripted reviewer for evals.
- **Libraries:** `langgraph-checkpoint-sqlite`, `streamlit`.
- **Runs:** two new approval policies × 70 tasks × 3 trials.
- **Experiment:**
  - Policy variants (none, all writes, risk-tiered): unsafe actions, attack success, approval requests per 100 tickets.
  - Crash recovery: kill the process at each step and after a committed write, resume, and check the end state and that no write happened twice.
- **Done when:** a killed run resumes to the correct database state with no duplicate write; approve, edit, reject and cancel are tested; the audit log can reconstruct any run; write-up committed.
- **Effort and cost:** 10–12 hours, about $3.

#### Stage 9. Multi-agent (ladder rung 4)

- **Learn:** a supervisor with subagents as tools and isolated context (orchestrator-workers); handoffs between peers that share message state; token multipliers; the MAST failure taxonomy; why only one agent should write.
- **Questions:**
  - What does context isolation buy, and what does it lose?
  - Where do multi-agent systems fail?
  - Under which conditions does multi-agent measurably beat a single agent here?
- **Build:** `framework/multi/supervisor.py` (specialists for orders, refunds and policy; a single writer); `framework/multi/handoffs.py` (triage to specialist); the parallel task set; a stress variant of the environment with generated distractor tools, about 30 in total.
- **Libraries:** no additions; both patterns are built directly on LangGraph.
- **Runs:** supervisor on v1 50 × 3; handoffs on 25 tasks × 3; parallel set 20 × 5 for single and supervisor; stress set 15 × 3 for single and supervisor.
- **Experiment:** single agent versus supervisor versus handoffs: success, pass^k, cost, latency, model calls, token multiplier, and failure categories.
  - Cost and token multipliers will be clear.
  - A success difference on the parallel set is resolvable only if it is large.
  - The stress set is exploratory.
- **Done when:** the paired table exists with the detectable difference stated; the write-up says plainly whether multi-agent earned its cost; write-up committed.
- **Effort and cost:** 12–16 hours, about $9.

#### Stage 10. Patterns: plan-and-execute, reflection, evaluator-optimizer (advanced)

- **Learn:** fixing a plan before reading untrusted data (also a security pattern); reflection by self-critique versus a separate evaluator; parallel fan-out with `Send`; the price of extra calls.
- **Questions:**
  - When does an explicit plan beat a plain tool loop?
  - Why does a separate evaluator do better than self-critique?
  - What does each extra call cost per point of success gained?
- **Build:** `framework/patterns/plan_execute.py`; `framework/patterns/evaluator_optimizer.py` (a verifier checks the proposed action and reply against policy, at most two revisions) with a self-critique variant; fan-out for audit tickets.
- **Libraries:** no additions.
- **Runs:** separate evaluator 50 × 3; self-critique 25 × 3; plan-and-execute 25 × 3 plus adversarial 20 × 3.
- **Experiment:** graph agent versus each pattern, paired: success, cost, latency, attack success.
- **Done when:** the table exists; only patterns that beat the baseline beyond the detectable difference are kept, and the write-up says so if none do.
- **Effort and cost:** 8–10 hours, about $3.50.

#### Stage 11. MCP (advanced)

- **Learn:** MCP tools, resources and prompts; stdio and streamable HTTP transports; what the July 2026 revision changed; tool poisoning and changed-after-approval attacks.
- **Questions:**
  - What does MCP standardise that plain function calling does not?
  - When is the extra hop worth it?
  - How can a server attack my agent, and what stops it?
- **Build:** `framework/mcp_server/` exposing the store tools over stdio with the official SDK; a small hand-written bridge from MCP tools to LangGraph tools; pinning of tool definitions by hash; a deliberately poisoned server for tests.
- **Libraries:** `mcp` 2.x. The LangChain adapter pins `mcp<2`, so the fallback is the adapter with the older SDK.
- **Runs:** v1 through MCP 50 × 3; poisoning 10 × 3, pinning off and on.
- **Experiment:** in-process tools versus MCP for latency per call; the poisoned-description attack with and without pinning.
- **Done when:** scripted parity passes through MCP; the pin check catches the poisoned server; write-up committed.
- **Effort and cost:** 8–10 hours, about $2.

#### Stage 12. Memory, context management and prompt caching (advanced)

- **Learn:** thread state versus a cross-thread store; facts, past events and procedures as kinds of memory; trimming and summarising context; prompt caching on both providers; memory as an attack surface.
- **Questions:**
  - What should be remembered, and when is it written?
  - When does context trimming hurt?
  - What breaks a prompt cache?
  - How does a poisoned memory make an attack persist?
- **Build:** a LangGraph `Store` for customer history; a write policy that validates what is stored; context trimming for long threads; cache-friendly prompt ordering; 12 multi-ticket sequence tasks and 5 long-thread tasks.
- **Libraries:** no additions.
- **Runs:** sequences 12 × 3, memory off and on; long threads 5 × 3, trimming off and on; v1 50 × 1, caching off and on.
- **Experiment:** sequence success with and without memory; tokens and cost with and without trimming and caching; a memory-poisoning test.
- **Done when:** the tables exist; the poisoning test and its mitigation are documented; the variant to deploy is chosen from the numbers and recorded; write-up committed.
- **Effort and cost:** 8–10 hours, about $2.

### Sub-project 3: Ops (deploys the chosen agent, builds no new one)

#### Stage 13. Serve, containerise, deploy

- **Learn:** an API for long-running runs (start, stream, status, resume, cancel); stateless compute over persisted state; secrets; infrastructure as code; cold starts and time limits; the risk of a public endpoint that spends money.
- **Questions:**
  - Why can an approval resume on a different instance?
  - What does Lambda limit, and when would I move to Fargate?
  - How do I stop strangers spending my API budget?
- **Build:**
  - `ops/app/`: FastAPI with start, resume, cancel and a server-sent-events stream. Status is a checkpoint read, not a running job.
  - `ops/Dockerfile`: Python 3.13 slim with the Lambda Web Adapter in response-stream mode, arm64.
  - `DynamoDBSaver` from `langgraph-checkpoint-aws` for checkpoints.
  - The demo store saved per session in S3, written inside the tool call with a conditional put, with the idempotency ledger in the same file.
  - `ops/terraform/`: ECR, Lambda with a 120-second timeout, function URL, DynamoDB, S3, IAM, logs.
  - Secrets in SSM Parameter Store; an API key check; a daily spend cap held in a DynamoDB counter.
  - The Streamlit client pointed at the deployed URL.
- **Libraries:** `fastapi`, `boto3`, `langgraph-checkpoint-aws`; Terraform; Docker.
- **Experiment:** cold versus warm latency; time to first streamed event; approval resumed across instances; cost per request split between model and AWS.
- **Done when:** `terraform apply` on a clean account yields a working URL; an approval round trip works in the cloud; the spend cap trips in a test; teardown is documented; the write-up compares Lambda, ECS Express Mode and Bedrock AgentCore.
- **Effort and cost:** 14–18 hours, about $0.50 of API use, AWS about $0–1 a month.

#### Stage 14. Monitoring, cost tracking and online evals

- **Learn:** what to watch for an agent (steps, tool error rate, guardrail trips, approval rate, cost and latency per run); sampling; online versus offline evals; alerting; version tagging; judge drift.
- **Questions:**
  - Which offline metric has an online proxy?
  - How do I notice quality drift without labels?
  - What deserves an alert and what belongs on a dashboard?
- **Build:** structured logs and CloudWatch metrics, a dashboard and alarms; an AWS Budgets alert; release tags in Langfuse; a synthetic traffic script replaying held-out tickets; a scheduled online eval (a GitHub Actions cron job that samples traces, applies the stage 4 judge and the trajectory rules, and writes scores back).
- **Libraries:** `boto3`, the Langfuse API.
- **Runs:** 200 synthetic requests; 100 judge calls; 100 requests for the drill.
- **Experiment:** deploy a deliberately degraded version and measure how long each signal takes to catch it. Re-label 20 production replies to check the judge still agrees with you.
- **Done when:** an alarm fires in a test; online scores appear per release; the drill and the judge re-check are documented; write-up committed.
- **Effort and cost:** 8–10 hours, about $2.50.

#### Stage 15. Evals in CI and release gating

- **Learn:** a test pyramid for agents (scripted-model tests, canary tasks, a small live smoke eval, the full sweep); gating on noisy metrics; cost control and secrets in CI.
- **Questions:**
  - What should block a merge and what should only report?
  - How do I set a threshold given my noise?
- **Build:** GitHub Actions workflows:
  - Every pull request: lint, unit tests and guardrail tests with the scripted model, no API calls. This is the hard gate.
  - On a label or on main: a smoke eval of 12 canary tasks that have passed every past trial, with a $0.25 cap.
  - Manual: the full sweep compared with the stored baseline.
  - On a tag: build the image, push to ECR and deploy through OIDC.
  - The README results table generated from `results/`.
- **Libraries:** GitHub Actions, `ruff`.
- **Runs:** smoke eval about 15 times; one full sweep; ten smoke reruns of unchanged main.
- **Experiment:** one pull request with a harmful prompt change and one with a harmless refactor; ten reruns to bound the false-alarm rate.
- **Done when:** the gate blocks the first pull request and passes the second; CI cost per run is documented; the README has the architecture diagram and results table; write-up committed.
- **Effort and cost:** 6–8 hours, about $2.50.

## Budget and timeline

| Sub-project | Stages | Hours | API cost |
|---|---|---|---|
| 1. Foundations | 0–6 | 76–92 | about $18 |
| 2. Framework | 7–12 | 58–72 | about $23.50 |
| 3. Ops | 13–15 | 28–36 | about $5.50 |
| **Total** | 16 stages | **162–200** | **about $47** |

**Timeline.** 13–16 weeks at 12–13 hours a week. The four ladder rungs are complete at the end of stage 9.

**Cost basis.** I assumed a loop run is about 8 model calls, 45,000 input tokens and 2,000 output tokens: about $0.006 on the primary model, $0.055 on Haiku 4.5, $0.14 on a reference model, and about $0.005 per judge call. A multi-agent run is taken as two to three times a single-agent run. These are estimates; stage 2 replaces them with measured numbers.

**Why the primary must stay cheap.** Haiku-class costs about nine times as much per run. Moving all sweeps to it would put the total near $250, so it is only ever used on 15-task cross-checks.

**Cost control.** The runner prints an estimate before each run, enforces a hard cap, and records spend in `results/spend.csv`.

**If time or money runs short, cut in this order:**
1. Stage 10 (patterns): saves 8–10 hours and $3.50.
2. Stage 12 (memory and caching): saves 8–10 hours and $2.
3. The handoffs arm and the stress set in stage 9: saves about 4 hours and $3.
4. The `create_agent` comparison in stage 7: saves about 2 hours.

## Repository structure

```
agent-reliability-lab/
├── README.md                 overview, architecture diagram, results table
├── pyproject.toml            one package `arl`; extras: framework, ops, dev
├── requirements/             pinned versions per extra
├── .env.example
├── config/
│   ├── models.yaml           model ids, providers, prices
│   └── profiles/             dev, measure, reference
├── src/arl/
│   ├── env/                  shared: store, seed, policy, tools, faults
│   ├── llm/                  shared: types, two provider adapters, pricing
│   ├── tracing/              shared: JSONL events, Langfuse export
│   ├── evals/                shared: tasks/, graders/, runner, report, labels/
│   ├── guardrails/           shared: limits, loop detection, permissions, validation
│   ├── foundations/          sub-project 1: single_round.py, hand_loop.py
│   ├── framework/            sub-project 2: graph_agent, workflow, hitl, multi/,
│   │                         patterns/, mcp_server/, memory
│   └── cli.py                arl run | eval | report | label
├── ops/                      sub-project 3: app/, Dockerfile, terraform/,
│                             monitoring/, online_evals/
├── tests/                    unit, scripted-model and guardrail tests
├── results/                  one JSON per eval run, spend.csv
├── docs/
│   ├── stages/               00 to 15, one write-up each
│   ├── awareness/            short notes on topics not built
│   └── failure-taxonomy.md
└── .github/workflows/        ci, smoke-eval, full-eval, deploy
```

Each sub-project directory has its own README stating what it adds and how to run it.

## Tech stack

| Choice | Reason |
|---|---|
| Python 3.13 in a virtualenv, `pip` with pinned requirement files | Your machine has only 3.14; LangGraph declares support up to 3.13 |
| `openai` 3.x (Responses API) and `anthropic` 1.x (Messages API) | The raw SDKs show the wire format the framework later hides |
| Hand-written provider adapter, then `init_chat_model` | Two providers is small enough to write; avoids a proxy dependency |
| `pydantic` 2 | Tool argument schemas and validation from one definition |
| SQLite | A deterministic, resettable environment with no services to run |
| Own eval harness on `pytest` conventions | Writing graders is the learning goal; no framework to hide them |
| Langfuse Cloud (free tier) plus a local JSONL log | One backend from hand loop to deployed service; the local log is the audit trail |
| LangGraph 1.2 with LangChain 1.4 | Explicit state, checkpoints and interrupts; see sub-project 2 |
| `mcp` 2.x official SDK | Implements the current specification |
| Typer CLI and a thin Streamlit app | Minimal interface for running, labelling and approving |
| FastAPI | Async, streaming, and runs unchanged on Lambda through the Web Adapter |
| Lambda container image with a function URL | Scales to zero and costs about nothing at demo traffic |
| DynamoDB through `langgraph-checkpoint-aws` | Serverless checkpoint store inside the always-free allowance |
| SSM Parameter Store | Free secret storage |
| Terraform | Reproducible infrastructure in a widely used tool |
| GitHub Actions | Free CI, scheduled jobs and deploys through OIDC |

## Awareness only

Each gets a short note in `docs/awareness/` and is not built.

| Topic | Why not built |
|---|---|
| A2A and other agent-to-agent protocols | There is no second party's agent to talk to |
| Computer use and browser agents | A different modality; slow, costly and hard to grade |
| Code-execution sandboxes, programmatic tool calling, "code mode" | Needs sandbox infrastructure the use case does not call for |
| Tool search and deferred tool loading | Pays off above roughly ten tools; the stage 9 stress set shows the problem it solves |
| Durable execution engines (Temporal, DBOS, Restate, Lambda durable functions) | Checkpointing covers the idea at this scale; the stage 8 write-up explains the gap |
| Managed agent platforms (LangSmith Deployment, Bedrock AgentCore, Anthropic Managed Agents) | They hide the operations you want to learn; compared in the stage 13 write-up |
| Other frameworks (OpenAI Agents SDK, Claude Agent SDK, Pydantic AI, Google ADK, Microsoft Agent Framework, CrewAI, Deep Agents) | One framework learned deeply beats several skimmed; a comparison table goes in the stage 7 write-up |
| CaMeL and classifier-based injection detectors | Research-grade, or shown insufficient alone; stage 6 builds the structural defences |
| Guardrail libraries (NeMo Guardrails, Guardrails AI) | Hand-rolling shows the mechanics; noted as the production alternative |
| Red-team tools (garak, PyRIT, promptfoo) and public benchmarks (tau2-bench, AgentDojo, GAIA, SWE-bench Pro) | Useful to know by name; our own task sets do the same job at this scale |
| OpenTelemetry GenAI conventions | Still not stable; Langfuse's SDK already builds on OpenTelemetry |
| Retrieval at scale, vector databases | The policy document fits in the prompt |
| Fine-tuning and prompt optimisation (DSPy) | A separate skill that needs the eval harness first |

## Setup needed and risks

**Before stage 0**
- Install Python 3.13 from python.org and create a virtualenv.
- `git init`, and create the GitHub repository.
- Put the OpenAI key in `.env` (never committed); the Anthropic key is needed from stage 1.
- Create a free Langfuse Cloud account.

**Before stage 13**
- Install Docker Desktop or OrbStack (Docker is not on your machine), the AWS CLI and Terraform.
- Set an AWS Budgets alert before deploying anything.

**Risks**

| Risk | Handling |
|---|---|
| The cheapest model is too weak or too strong to give informative results | Stage 2 chooses among three cheap models by measurement |
| Spend exceeds $50 | Hard cap per run, a ledger, and the cut list above |
| Results differ by less than the noise | Paired comparisons; each write-up states the detectable difference |
| Prompts get tuned to the eval set | A held-out split, run only at milestones |
| The judge drifts as agents change | Re-label 20 replies at stages 9 and 14 |
| The LangChain MCP adapter pins the old SDK | Stage 11 writes a small bridge, with the older SDK as fallback |
| Langfuse's free tier fills during sweeps | Sweeps export at most 30 traces; the local log stays complete |
| A resumed or retried run repeats a write | Approval gate in its own node, idempotency keys from the tool-call id, tested in stage 8 |
| A public endpoint runs up cost | API key, 120-second timeout, daily cap, budget alert, documented teardown |
| `claude-haiku-4-5` may be retired (earliest date 15 October 2026) | Models are config, so it is a one-line change |

## Verification

- **Every stage:** `pytest` passes; `arl eval` regenerates that stage's table from a clean checkout; the write-up is committed.
- **Guardrails (stages 5 and 6 onward):** each scripted-model test fails with the guardrail disabled and passes with it enabled.
- **Judge (stage 4):** the held-back label set is scored once and the rates are reported as measured.
- **Parity (stages 7 and 11):** the scripted model produces identical tool-call sequences in the old and new implementation.
- **Recovery (stage 8):** a run killed after a committed write resumes with no duplicate write.
- **Deployment (stage 13):** a request to the live URL completes an approval round trip, and the spend cap trips in a test.
- **CI (stage 15):** the harmful pull request is blocked and the harmless one passes.

## How we work after approval

We build stage 0 only. At the start of each stage I explain the concept and propose the design; you approve it; we build, run the experiment and write it up; then we stop until you are ready for the next stage.

## Sources

- Workflows and agents: [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Anthropic, Harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps) · [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- Frameworks: [LangChain and LangGraph 1.0](https://www.langchain.com/blog/langchain-langgraph-1dot0) · [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) · [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) · [langgraph-supervisor (archived)](https://github.com/langchain-ai/langgraph-supervisor-py)
- Multi-agent: [Anthropic research system](https://www.anthropic.com/engineering/multi-agent-research-system) · [Cognition, Multi-agents working](https://cognition.com/blog/multi-agents-working) · [Google, Scaling agent systems](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) · [MAST](https://arxiv.org/abs/2503.13657)
- Tools and MCP: [Anthropic, Writing tools for agents](https://anthropic.com/engineering/writing-tools-for-agents) · [OpenAI, Migrate to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses) · [MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) · [MCP security best practices](https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices)
- Security: [Willison on Rule of Two and adaptive attacks](https://simonw.substack.com/p/new-prompt-injection-papers-agents) · [Design patterns for securing agents](https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/)
- Evals: [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) · [Hamel Husain, LLM judges](https://hamel.dev/blog/posts/llm-judge/) · [Judge agreement study](https://arxiv.org/abs/2606.19544) · [tau-bench](https://arxiv.org/abs/2406.12045)
- Observability: [Langfuse pricing](https://langfuse.com/pricing) · [Langfuse joins ClickHouse](https://langfuse.com/blog/joining-clickhouse) · [LiteLLM security update](https://docs.litellm.ai/blog/security-update-march-2026)
- Pricing: [OpenAI pricing](https://developers.openai.com/api/docs/pricing) · [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- AWS: [App Runner availability change](https://docs.aws.amazon.com/ja_jp/apprunner/latest/dg/apprunner-availability-change.html) · [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) · [Lambda response streaming](https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html) · [DynamoDB as a LangGraph checkpoint store](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ddb-langgraph-checkpoint.html) · [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) · [Lambda Web Adapter streaming example](https://github.com/awslabs/aws-lambda-web-adapter/blob/main/examples/fastapi-response-streaming-zip)
