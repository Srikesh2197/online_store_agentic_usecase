# Agent Reliability Lab: 6-week plan

## Context

You want to learn how agentic AI systems work in practice, with the repository as the byproduct. Success means you can explain when an agent is the right tool, how to design, bound, evaluate and operate one, and what each choice trades off, using numbers from your own runs. Your priorities are bounded behaviour, auditability, evaluation and human oversight.

This version fits the whole project into **6 weeks at about 15 hours a week (90 hours)**. It touches every important topic once, at reduced depth. The fuller 16-stage version (160–200 hours) is saved at `plan-full-16-stages.md` in the project folder for when you want to go deeper.

The folder `/Users/luffy/Desktop/Projects/Agentic_AI` holds only that saved plan and is not yet a git repository. No code is written until you approve this plan, and then we build one stage at a time.

## What the 6-week limit costs

1. **There is no slack.** The 12 stages add up to exactly 90 hours. A cut order is in "Schedule and budget".
2. **I write most of the code.** Your hours go to reading it, reading traces, writing tasks, labelling, running experiments and deciding. That is how 90 hours covers this much.
3. **Results are mostly directional.** With 30 tasks, only large differences in success rate (roughly 20 points or more) can be told apart from noise. Cost, latency and step counts stay precise. Each write-up says which kind of result it is.
4. **Three topics become tasters and one moves to awareness.** Evaluator-optimizer, MCP and long-term memory share one stage. Plan-and-execute is explained but not built.

## Decisions already made

| Decision | Choice |
|---|---|
| Time limit | 6 weeks, about 90 hours |
| Use case | Support-operations agent for a simulated online store |
| Packaging | One repository, three sub-projects (foundations, framework, ops) |
| Deployment | AWS Lambda container image, function URL, DynamoDB checkpoints |
| Build order | All agent stages first, ops last, deploying the best-measured variant |
| API budget | About $50 in total |
| Starting point | You have made chat calls but not written tool calling or a loop |

## What the research found

Sources are listed at the end. Findings that shaped the plan:

1. **Simplest thing first is the consensus.** Anthropic, OpenAI and Microsoft all advise a workflow or a single call before an agent.
2. **ReAct is now "a model calling tools in a loop".** LangChain deprecated `create_react_agent` in favour of `create_agent` plus middleware.
3. **Multi-agent helps parallel work and hurts sequential work.** A Google/MIT study measured +81% on a parallelisable task and −39% to −70% on sequential ones. Anthropic reports about 15× the tokens of a chat. Cognition's current position is that it works when only one agent writes.
4. **Reflection works with a separate evaluator, not self-critique.** Anthropic found agents "confidently praise" their own work.
5. **Injection detectors alone do not hold.** A joint OpenAI/Anthropic/DeepMind paper broke 12 published defences with adaptive attacks at over 90% success. Durable defences are structural: restrict what the agent can do after it reads untrusted content (Meta's "Rule of Two").
6. **Eval practice has settled.** Start with 20–50 tasks, grade outcomes over paths, run several trials, and report pass^k (the share of tasks that succeed on all k trials). Validate a binary judge against human labels using true-positive and true-negative rates.
7. **Tool design matters more than tool count.** Few workflow-level tools, long descriptions that say when not to use them, actionable error messages, bounded response sizes.
8. **Things that changed recently:**
   - The MCP specification of 28 July 2026 is stateless and not backward compatible. `langchain-mcp-adapters` 0.3.2 still pins the older SDK (`mcp<2`).
   - The OpenAI Assistants API is gone; the Responses API is the default.
   - Newer Claude models reject forced `tool_choice` and non-default `temperature`, so "temperature 0" is not available for determinism.
   - `langgraph-supervisor` is archived; the supervisor pattern is built directly with subagents as tools.
   - AWS App Runner closed to new customers on 30 April 2026.
   - LiteLLM shipped two malicious PyPI releases in March 2026.
9. **Tracing backends.** Langfuse is MIT-licensed, built on OpenTelemetry, and works with a hand-written loop and with LangGraph. Its free cloud tier is 50,000 units a month, where every trace, span and score counts.

## Topic tiers

| Tier | Topics | Why here |
|---|---|---|
| **Core (built properly)** | Tool calling and tool design · hand-written loop (ReAct) · eval harness (outcome checks, trajectory checks, pass^k, cost, latency) · LLM judge validated on your labels · tracing · limits, loop detection, validation, retries · tool permissions · prompt-injection tests · workflow versus agent (routing, chaining) · LangGraph state and checkpointing · human approval and interruption · multi-agent (supervisor, handoffs) · deployment and operation | The four ladder rungs plus the reliability mechanics you named |
| **Taster (built small, one measurement each)** | Reflection and evaluator-optimizer · MCP server and client · long-term memory | Each is worth meeting once in code; depth can wait |
| **Awareness only (explained, not built)** | See the section near the end | Needs infrastructure or time this version does not have |

## Use case and concept coverage

**Candidates considered**

- **A. Support operations.** Reads tickets, looks up orders, applies a written policy, and issues refunds, cancellations and address changes against a local SQLite database.
- **B. Data analyst.** Answers questions over public databases with SQL and Python, using BIRD Mini-Dev.
- **C. Research agent.** Answers multi-hop questions over Wikipedia and arXiv.

| Concept | A. Support ops | B. Data analyst | C. Research | Stage |
|---|---|---|---|---|
| Multi-step use of real tools | Strong | Strong | Strong | 0, 1, 3 |
| Tracing | Strong | Strong | Strong | 0 onward |
| Objectively checkable outcome | Strong (database end state) | Strong (result match) | Partial (live data drifts) | 2 |
| Trajectory rules worth checking | Strong (verify before write) | Partial | Partial | 2 |
| ReAct tool loop | Strong | Strong | Strong | 3 |
| LLM judge has a real job | Strong (reply quality) | Weak | Strong | 4 |
| Limits, retries, tool failure handling | Strong (injected) | Partial | Strong | 5 |
| Permissions and indirect prompt injection | Strong | Partial | Partial | 5 |
| Workflow versus agent; routing and chaining | Strong | Partial | Partial | 6 |
| Checkpointing, approval, interruption | Strong | Weak | Partial | 7 |
| Multi-agent: supervisor, handoffs, shared versus isolated state | Partial | Partial | Strong | 8 |
| Reflection, evaluator-optimizer | Strong | Strong | Strong | 9 |
| MCP | Strong | Strong | Strong | 9 |
| Long-term memory has a purpose | Strong (customer history) | Partial | Partial | 9 |
| Deployment and operation | Strong | Strong | Strong | 10, 11 |
| Deterministic and cheap to re-run | Strong | Strong | Weak | all |

**Why A.** Bounded behaviour, auditability and oversight only have teeth when the agent can change something, and A is the only candidate with write actions. Outcomes are checked by comparing database state, the method tau-bench uses.

## Why one repository with three sub-projects

- **The eval set and environment are the spine.** Comparing ladder rungs is only valid if every agent runs through the identical harness on the identical tasks.
- **Each sub-project has a distinct dependency footprint**, exposed as install extras, so "what each layer adds" is visible in the dependency list.
- **Ops builds no agent.** It imports the agent chosen at the end of sub-project 2 and deploys it.

| Sub-project | Stages | Contains | Installs |
|---|---|---|---|
| 1. Foundations | 0–5 | Rungs 1 and 2, eval harness, judge, guardrails | `openai`, `anthropic`, `pydantic`, `langfuse` |
| 2. Framework | 6–9 | Rung 3 (LangGraph), approval, rung 4 (multi-agent), tasters | adds `langgraph`, `langchain`, `mcp` |
| 3. Ops | 10–11 | Serving, container, AWS, monitoring, online evals, CI | adds `fastapi`, `boto3`, `langgraph-checkpoint-aws` |

## The shared spine

**Environment.** A SQLite store seeded deterministically: customers, orders, items, shipments, refunds. A written policy document sets the rules. About ten tools: five read, four write, one escalate. Each trial starts from a fresh copy of the database.

**Task format.** One YAML file per task: the ticket, the expected database change, the expected disposition (resolved, refused or escalated), facts the reply must contain, trajectory rules (must call, must not call, ordering), and a provenance tag.

**Task sets**

| Set | Size | Frozen at | Purpose |
|---|---|---|---|
| Capability v1 | 30 tasks: 20 written up front, 10 drawn from observed failures | End of stage 4 | Main comparisons |
| Adversarial | 12 tasks | End of stage 5 | Injection, runaway-loop bait, tool faults |
| Parallel | 8 bulk-audit tasks | Stage 8 | Gives multi-agent a fair test |

The 20 original and 10 failure-derived tasks are reported separately, because the second group was selected to be hard for the early rungs.

**Metrics.** The headline is code-graded success: the database end state and trajectory rules, with no model in the grading. Also reported: pass^k, model calls per run, tokens, dollars per run, and latency. From stage 5: unsafe-action rate and attack success rate. The judge's reply-quality score is a separate column.

**How comparisons are reported.** Every comparison is paired by task (wins, losses, ties). Each write-up states the smallest difference the experiment could detect and says whether the result is a finding or a direction.

**Models.** The primary model stays in the cheapest tier. Stage 2 picks it by measurement.

| Role | Candidates | Price per million tokens (input / output) |
|---|---|---|
| Primary (nearly all runs) | `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5-mini` | $0.10 / $0.50 to $0.25 / $2.00 |
| Secondary (cross-provider check on 10 tasks) | `claude-haiku-4-5` | $1 / $5 |
| Reference (10 hard tasks, once) | `claude-sonnet-5-5` or `gpt-6.1-sol` | $2 / $10 |
| Judge | A different model family from the agent | Haiku-class |

**Tracing.** Every model call and tool call is written to a local JSONL event log. The graders read it, the write-ups cite it, and it is the audit trail. Interactive runs also go to Langfuse. Sweeps export at most 30 traces each, to stay inside the free tier.

**Testing with a scripted model.** A fake model that replays a fixed sequence of tool calls drives the unit tests. It makes guardrail tests deterministic and free. It proves code-enforced rules hold; attack success and recovery come from live runs and are reported as rates.

**Stage write-ups.** Each stage ends with a one-page `docs/stages/NN-name.md`: the concept, the options, what we chose, the measured result, and when you would choose differently in production.

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
- **Effort and cost:** 5 hours, about $0.25.

#### Stage 1. Two providers and the full toolset

- **Learn:** how OpenAI's Responses API and Anthropic's Messages API differ in representing calls, results and stop reasons; what a provider-neutral interface has to hide; designing write tools.
- **Questions:**
  - Which differences are cosmetic and which change how a loop must behave?
  - What should a tool return on bad input?
- **Build:** the same single round against the second provider; then `llm/` (neutral message types, two adapters, a price table from config); the remaining tools including the four write tools, with Pydantic argument models and actionable errors.
- **Libraries:** adds `anthropic`.
- **Experiment:** the same five tickets on both providers; compare the traces side by side.
- **Done when:** one config switch moves a ticket between providers; adapters are tested against recorded responses; the write-up has a table of provider differences.
- **Effort and cost:** 5 hours, about $0.25.

#### Stage 2. Eval harness and baseline

- **Learn:** the vocabulary (task, trial, grader, transcript, outcome); outcome grading versus trajectory grading; non-determinism and pass^k; paired comparison; why the harness comes before the agent.
- **Questions:**
  - What makes a task unambiguous enough to grade?
  - Why grade the end state instead of the steps, and when is a step rule still justified?
  - How large a difference can I trust at this sample size?
- **Build:** the first 20 tasks; `evals/graders/outcome.py` (database diff, reply facts); `evals/graders/trajectory.py` (must-call, must-not-call, ordering); `evals/runner.py` (fresh database per trial, k trials, cost cap, dry-run estimate); `evals/report.py` (paired comparison table); a spend ledger.
- **Libraries:** `pytest`, `pyyaml`.
- **Runs:** single round, 20 tasks × 5 trials on the primary; 20 × 1 on two other cheap models and on Haiku.
- **Experiment:** baseline for rung 1 with per-task variance; pick the primary and secondary models from graded results.
- **Done when:** `arl eval` reproduces the table from a clean checkout; graders are unit-tested with hand-made passing and failing transcripts; you have read 10 transcripts and confirmed the grader verdicts; the cost cap halts a run in a test; later cost estimates are replaced with measured ones; write-up committed.
- **Effort and cost:** 10 hours, about $1.50.

#### Stage 3. Hand-written agent loop (ladder rung 2, the ReAct pattern)

- **Learn:** the loop itself (call, run tools, return results, repeat); message history; stop reasons; parallel tool calls; tool errors as feedback to the model.
- **Questions:**
  - What ends the loop, and what happens on a truncated response, a refusal or malformed arguments?
  - What does the loop add over one round, in success and in cost?
  - Does a better loop or a better model buy more?
- **Build:** `foundations/hand_loop.py`, roughly 150 lines, working with both providers; stop-reason handling; tool errors returned as error results; a plain step cap as the only safety net for now; the scripted fake model for tests.
- **Libraries:** no additions.
- **Runs:** loop, 20 × 5 on the primary; 10 × 1 on Haiku; 10 × 1 on the reference model.
- **Experiment:** rung 1 versus rung 2, paired by task. This difference should be large enough to resolve.
- **Done when:** the loop passes scripted-model tests covering each stop reason; the comparison table exists; you have read and annotated ten failed traces; write-up committed.
- **Effort and cost:** 7 hours, about $3.50.

#### Stage 4. Error analysis and a validated LLM judge

- **Learn:** reading traces and grouping failures into a taxonomy; which failures code can check and which need a judge; binary verdicts with a written critique; validating a judge with true-positive and true-negative rates; judge biases.
- **Questions:**
  - Why binary instead of a 1–5 scale?
  - Why is raw agreement misleading?
  - When is a judge trustworthy enough to gate a release?
- **Build:** `arl label` (a command-line labelling prompt: pass or fail plus a one-line critique); `evals/graders/judge.py` (rubric, reasoning before verdict, structured output, trimmed input); `evals/judge_validation.py` (confusion matrix, rates, kappa, intervals); `docs/failure-taxonomy.md`; 10 more tasks drawn from observed failures; freeze capability set v1.
- **Libraries:** no additions.
- **Runs:** about 200 judge calls; rung 1 and rung 2 re-run on v1 at 30 × 5.
- **Experiment:**
  - You label 60 replies from stages 2 and 3, aiming for an even pass/fail mix. Split 10 as examples, 20 for tuning, 30 held back.
  - Tune the judge prompt on the tuning set, then score the held-back set once.
  - Re-run rungs 1 and 2 on frozen v1 to set the reference baseline.
- **Done when:** the validation report states held-back rates with their intervals. With 30 held-back labels the intervals are wide, so the judge stays advisory in this version and the write-up says so; v1 and its baseline are frozen; write-up committed.
- **Effort and cost:** 8 hours including about 1.5 hours of labelling, about $2.50.

#### Stage 5. Guardrails, failure handling and prompt injection as tested features

- **Learn:** step, token, dollar and wall-clock limits; loop detection; argument validation; retries and idempotency; read and write permission tiers; direct and indirect prompt injection; why prompt-only defences are not enough.
- **Questions:**
  - Which guardrail belongs in the prompt, which in the loop, and which inside the tool?
  - What should the agent do when a limit trips?
  - How can a retry cause a double refund?
  - What is my attack success rate before and after?
- **Build:**
  - `guardrails/limits.py`, `guardrails/loopdetect.py`, `guardrails/validation.py`.
  - `env/faults.py`: a seeded fault injector (timeout, server error, failure after commit).
  - Retries with backoff; idempotency keys on write tools, derived from the run id and the model's tool-call id.
  - `guardrails/permissions.py`: tiers, and a taint flag that blocks or escalates writes after untrusted content is read.
  - Policy invariants enforced in code inside write tools (a refund cannot exceed the amount paid; the order must belong to the verified customer).
  - The adversarial task set, calibrated so the unguarded attack success rate is at least 40%.
- **Libraries:** `tenacity`.
- **Runs:** adversarial 12 × 5 with guardrails off, prompt-only defence, and all on; v1 at 30 × 5 with all on.
- **Experiment:** attack success, unsafe actions, runaway runs and double writes across the three arms. All guardrails on versus the stage 4 baseline on v1 for the cost in normal success.
- **Done when:** each guardrail has a scripted-model test that fails without it and passes with it; the live table shows rates per arm; the write-up lists which attacks still succeed; the adversarial set is frozen.
- **Effort and cost:** 11 hours, about $3.50.

### Sub-project 2: Framework (LangGraph)

**Why LangGraph.** State and control flow are explicit, which serves auditability. Checkpointing and interrupts are first-class, which serves oversight. It has been stable at 1.x since October 2025, is MIT-licensed, works with both providers, and has SQLite, Postgres and DynamoDB checkpoint stores.

**How it relates to LangChain.** LangChain 1.x `create_agent` is a ready-made agent loop built on the LangGraph runtime and extended through middleware. We use LangGraph's `StateGraph` directly so the mechanics stay visible, and write the `create_agent` version once in stage 6 to see what it hides.

**Known criticisms:** conceptual overhead for simple agents, API churn, and the point that a checkpoint is not durable execution (something must still notice the failure and resume).

#### Stage 6. Port to LangGraph and add a workflow (ladder rung 3)

- **Learn:** `StateGraph`, state schemas and reducers, nodes, conditional edges; what the framework gives and what it hides; routing and prompt chaining; workflow versus agent.
- **Questions:**
  - Which graph primitive does each part of my hand loop map to?
  - What did I get for free, and what can I no longer see?
  - When would I choose no framework, LangGraph, or `create_agent`?
  - What does a fixed workflow cost and gain against the agent?
- **Build:** `framework/graph_agent.py` (the same loop as a graph, reusing the stage 5 guardrails); `framework/workflow.py` (classify, route, a fixed chain per category, escalate otherwise); `framework/prebuilt_agent.py` (`create_agent`, read side by side with the graph, not evaluated); `init_chat_model` for provider switching; the Langfuse callback; a fake chat model that supports tool binding.
- **Libraries:** `langgraph` 1.2, `langchain` 1.4, `langchain-openai`, `langchain-anthropic`.
- **Runs:** graph agent 30 × 3; workflow 30 × 5; Haiku 10 × 1.
- **Experiment:**
  - Parity, proven with the scripted model: the hand loop and the graph agent must produce identical tool-call sequences.
  - Workflow versus agent on v1, paired: success, cost, latency.
- **Done when:** scripted parity passes; the adversarial set still passes; the comparison table exists; the write-up has a "what maps to what" table.
- **Effort and cost:** 8 hours, about $2.50.

#### Stage 7. Persistence, human approval and interruption

- **Learn:** checkpointers and threads; `interrupt()` and `Command(resume=...)`; the fact that a node re-runs from the top on resume; approve and reject; cancelling a run in flight; audit logs.
- **Questions:**
  - What exactly is saved at a checkpoint?
  - Why does approval require persistence?
  - What re-runs on resume, and why does that make write tools dangerous?
  - How do I decide what needs approval without overloading the reviewer?
- **Build:** SQLite checkpointing; an approval gate in its own node, placed before the node that runs writes; an approval policy (writes above a threshold, or any write after tainted input); approve and reject from the command line; cancellation of a running thread with its state kept; an audit log of who approved what; a scripted reviewer for evals.
- **Libraries:** `langgraph-checkpoint-sqlite`.
- **Runs:** two approval policies × 42 tasks × 3 trials.
- **Experiment:**
  - Policy variants (none, all writes, risk-tiered): unsafe actions, attack success, approval requests per 100 tickets.
  - Crash recovery: kill the process after a committed write, resume, and check that no write happened twice.
- **Done when:** a killed run resumes to the correct database state with no duplicate write; approve, reject and cancel are tested; the audit log can reconstruct a run; write-up committed.
- **Effort and cost:** 7 hours, about $2.

#### Stage 8. Multi-agent (ladder rung 4)

- **Learn:** a supervisor with subagents as tools and isolated context (orchestrator-workers); handoffs between peers that share message state; token multipliers; why only one agent should write.
- **Questions:**
  - What does context isolation buy, and what does it lose?
  - Where do multi-agent systems fail?
  - Did multi-agent earn its cost here?
- **Build:** `framework/multi/supervisor.py` (specialists for orders, refunds and policy; a single writer); `framework/multi/handoffs.py` (triage to specialist); the parallel task set.
- **Libraries:** no additions; both patterns are built directly on LangGraph.
- **Runs:** supervisor and handoffs on v1 at 30 × 3 each; parallel set 8 × 5 for single and supervisor.
- **Experiment:** single agent versus supervisor versus handoffs: success, cost, latency, model calls, token multiplier. Cost and token multipliers will be clear; success differences are directional at this size.
- **Done when:** the paired table exists; the write-up says plainly whether multi-agent earned its cost; write-up committed.
- **Effort and cost:** 7 hours, about $5.

#### Stage 9. Three tasters: evaluator-optimizer, MCP, long-term memory

- **Learn:** reflection with a separate evaluator; what MCP standardises and how a server can attack an agent; thread state versus a cross-thread store.
- **Questions:**
  - What does a verifier call cost per point of success gained?
  - What does MCP add over plain function calling, and what is tool poisoning?
  - What should an agent remember, and when is it written?
- **Build:**
  - `framework/patterns/evaluator.py`: a verifier checks the proposed action and reply against policy, with one revision.
  - `framework/mcp_server/`: the store tools over stdio with the official SDK, a small bridge to LangGraph tools, and a hash pin on tool definitions.
  - `framework/memory.py`: a LangGraph `Store` holding customer history notes; 6 two-ticket sequence tasks.
- **Libraries:** `mcp` 2.x. The LangChain adapter pins `mcp<2`, so the fallback is the adapter with the older SDK.
- **Runs:** evaluator 30 × 3; MCP 10 × 3; sequences 6 × 3 with memory off and on.
- **Experiment:** evaluator versus graph agent, paired; scripted parity through MCP and a scripted poisoned-description test; sequence success with and without memory. Prompt-cache hit rates are read from the usage data already logged.
- **Done when:** each taster has its small table or test; the variant to deploy is chosen from the numbers and recorded; one write-up covers all three and explains plan-and-execute.
- **Effort and cost:** 7 hours, about $2.

### Sub-project 3: Ops (deploys the chosen agent, builds no new one)

#### Stage 10. Serve, containerise, deploy

- **Learn:** an API for long-running runs (start, status, resume, cancel); stateless compute over persisted state; secrets; infrastructure as code; cold starts and time limits; the risk of a public endpoint that spends money.
- **Questions:**
  - Why can an approval resume on a different instance?
  - What does Lambda limit, and when would I move to Fargate?
  - How do I stop strangers spending my API budget?
- **Build:**
  - `ops/app/`: FastAPI with start, resume and cancel. Status is a checkpoint read, not a running job.
  - `ops/Dockerfile`: Python 3.13 slim with the Lambda Web Adapter, arm64.
  - `DynamoDBSaver` from `langgraph-checkpoint-aws` for checkpoints; the demo store saved per session in S3.
  - `ops/template.yaml` (AWS SAM): Lambda with a 120-second timeout, function URL, DynamoDB, S3, IAM.
  - Secrets in SSM Parameter Store; an API key check; a daily spend cap held in a DynamoDB counter.
- **Libraries:** `fastapi`, `boto3`, `langgraph-checkpoint-aws`; AWS SAM; Docker.
- **Experiment:** cold versus warm latency; approval resumed across instances; cost per request split between model and AWS.
- **Done when:** `sam deploy` yields a working URL; an approval round trip works in the cloud; the spend cap trips in a test; teardown is documented; the write-up compares Lambda, ECS Express Mode and Bedrock AgentCore.
- **Effort and cost:** 9 hours, about $0.50 of API use, AWS about $0–1 a month.

#### Stage 11. Operate: monitoring, cost tracking, online evals, evals in CI

- **Learn:** what to watch for an agent (steps, tool error rate, guardrail trips, cost and latency per run); online versus offline evals; a test pyramid for agents; gating on noisy metrics.
- **Questions:**
  - How do I notice quality drift without labels?
  - What deserves an alert and what belongs on a dashboard?
  - What should block a merge and what should only report?
- **Build:**
  - Structured logs with cost per request, one CloudWatch alarm, and an AWS Budgets alert.
  - An online eval script that samples recent traces and applies the trajectory rules and the stage 4 judge.
  - GitHub Actions: on every pull request, lint and scripted-model tests with no API calls (the hard gate); on a label, a smoke eval of 8 tasks that have passed every past trial, capped at $0.25.
  - The README architecture diagram and a results table generated from `results/`.
- **Libraries:** GitHub Actions, `ruff`, `boto3`.
- **Runs:** 50 synthetic requests; 50 judge calls; smoke eval about 10 times; one full sweep.
- **Experiment:** one pull request with a harmful prompt change, to confirm the gate blocks it; the online eval run over the synthetic traffic.
- **Done when:** the gate blocks the harmful pull request; the alarm fires in a test; online scores are produced; the README is complete; write-up committed.
- **Effort and cost:** 6 hours, about $2.

## Schedule and budget

| Week | Stages | Hours |
|---|---|---|
| 1 | 0, 1, first half of 2 | 15 |
| 2 | Rest of 2, 3, start of 4 | 15 |
| 3 | Rest of 4, 5 | 16 |
| 4 | 6, 7 | 15 |
| 5 | 8, 9 (and install the AWS tools) | 14 |
| 6 | 10, 11 | 15 |

| Sub-project | Stages | Hours | API cost |
|---|---|---|---|
| 1. Foundations | 0–5 | 46 | about $11.50 |
| 2. Framework | 6–9 | 29 | about $11.50 |
| 3. Ops | 10–11 | 15 | about $2.50 |
| **Total** | 12 stages | **90** | **about $25.50** |

**Cost basis.** I assumed a loop run is about 8 model calls, 45,000 input tokens and 2,000 output tokens: about $0.006 on the primary model, $0.055 on Haiku 4.5, $0.14 on a reference model, and about $0.005 per judge call. These are estimates; stage 2 replaces them with measured numbers.

**Spare budget.** The plan uses about half of your $50. Extra trials cost money but none of your time, so the remainder can raise trials from 5 to 10 on the main comparisons. The runner prints an estimate before each run, enforces a hard cap, and records spend in `results/spend.csv`.

**If a stage overruns, cut in this order:**
1. The handoffs arm in stage 8.
2. The memory taster in stage 9.
3. The evaluator taster in stage 9.
4. The workflow comparison in stage 6 (keep the port).

We check progress against the schedule at the end of each week and cut then, not at the end.

## What was trimmed, and where to go deeper later

The saved full plan covers each of these.

| Topic | In this plan | In the full plan |
|---|---|---|
| Task sets | 30 capability, 12 adversarial, 8 parallel | 50, 20 and 20, plus a held-out split |
| Judge validation | 60 labels, judge stays advisory | 150 labels, gating on a lower bound |
| Guardrails | One stage, three arms | Two stages, an arm per defence |
| Human approval | Approve and reject from the command line | Adds edit and a Streamlit inbox |
| Multi-agent | v1 and a small parallel set | Adds a 30-tool stress set |
| Patterns | Evaluator-optimizer only | Adds plan-and-execute and self-critique arms |
| MCP | Stdio, scripted parity and poisoning tests | Adds a live sweep and latency measurement |
| Memory | Customer notes, 6 sequence tasks | Adds context trimming, caching experiments, memory poisoning |
| Deployment | AWS SAM, request and response | Terraform, streaming responses, conditional writes |
| Operations | One alarm, online eval script, pull-request gate | Dashboards, scheduled online evals, regression drills, deploy on tag |

## Repository structure

```
agent-reliability-lab/
├── README.md                 overview, architecture diagram, results table
├── plan-full-16-stages.md    the saved fuller plan
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
│   └── cli.py                arl run | eval | report | label | approve
├── ops/                      sub-project 3: app/, Dockerfile, template.yaml,
│                             online_eval.py
├── tests/                    unit, scripted-model and guardrail tests
├── results/                  one JSON per eval run, spend.csv
├── docs/
│   ├── stages/               00 to 11, one write-up each
│   ├── awareness/            short notes on topics not built
│   └── failure-taxonomy.md
└── .github/workflows/        ci, smoke-eval
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
| Typer CLI | The only interface; no web app to maintain |
| FastAPI | Async, and runs unchanged on Lambda through the Web Adapter |
| Lambda container image with a function URL | Scales to zero and costs about nothing at demo traffic |
| DynamoDB through `langgraph-checkpoint-aws` | Serverless checkpoint store inside the always-free allowance |
| SSM Parameter Store | Free secret storage |
| AWS SAM | One template for Lambda, DynamoDB and S3; faster to learn than Terraform |
| GitHub Actions | Free CI |

## Awareness only

Each gets a short note in `docs/awareness/` and is not built.

| Topic | Why not built |
|---|---|
| Plan-and-execute | Time; explained in the stage 9 write-up, including its use as an injection defence |
| Context trimming and compaction | Time; tickets here are short enough not to need it |
| A2A and other agent-to-agent protocols | There is no second party's agent to talk to |
| Computer use and browser agents | A different modality; slow, costly and hard to grade |
| Code-execution sandboxes, programmatic tool calling, "code mode" | Needs sandbox infrastructure the use case does not call for |
| Tool search and deferred tool loading | Pays off above roughly ten tools |
| Durable execution engines (Temporal, DBOS, Restate, Lambda durable functions) | Checkpointing covers the idea at this scale; the stage 7 write-up explains the gap |
| Managed agent platforms (LangSmith Deployment, Bedrock AgentCore, Anthropic Managed Agents) | They hide the operations you want to learn; compared in the stage 10 write-up |
| Other frameworks (OpenAI Agents SDK, Claude Agent SDK, Pydantic AI, Google ADK, Microsoft Agent Framework, CrewAI, Deep Agents) | One framework learned properly beats several skimmed; a comparison table goes in the stage 6 write-up |
| CaMeL and classifier-based injection detectors | Research-grade, or shown insufficient alone; stage 5 builds the structural defences |
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

**Before stage 10** (worth doing in week 5 so week 6 is not lost to installs)
- Install Docker Desktop or OrbStack (Docker is not on your machine), the AWS CLI and the SAM CLI.
- Set an AWS Budgets alert before deploying anything.

**Risks**

| Risk | Handling |
|---|---|
| A stage overruns and there is no slack | Weekly check against the schedule; the cut order above |
| First AWS deployment takes longer than 9 hours | Tools installed in week 5; SAM instead of Terraform; no streaming |
| The cheapest model is too weak or too strong to be informative | Stage 2 chooses among three cheap models by measurement |
| Results differ by less than the noise | Paired comparisons; each write-up states the detectable difference |
| Prompts get tuned to a 30-task set with no held-out split | Stated as a limitation; the full plan adds the split |
| The LangChain MCP adapter pins the old SDK | Stage 9 writes a small bridge, with the older SDK as fallback |
| A resumed or retried run repeats a write | Approval gate in its own node, idempotency keys from the tool-call id, tested in stage 7 |
| A public endpoint runs up cost | API key, 120-second timeout, daily cap, budget alert, documented teardown |
| `claude-haiku-4-5` may be retired (earliest date 15 October 2026) | Models are config, so it is a one-line change |

## Verification

- **Every stage:** `pytest` passes; `arl eval` regenerates that stage's table from a clean checkout; the write-up is committed.
- **Guardrails (stage 5 onward):** each scripted-model test fails with the guardrail disabled and passes with it enabled.
- **Judge (stage 4):** the held-back label set is scored once and the rates are reported as measured.
- **Parity (stages 6 and 9):** the scripted model produces identical tool-call sequences in the old and new implementation.
- **Recovery (stage 7):** a run killed after a committed write resumes with no duplicate write.
- **Deployment (stage 10):** a request to the live URL completes an approval round trip, and the spend cap trips in a test.
- **CI (stage 11):** the harmful pull request is blocked.

## How we work after approval

We build stage 0 only. At the start of each stage I explain the concept and propose the design; you approve it; I write the code and you read it; we run the experiment and write it up together; then we stop until you are ready for the next stage.

## Sources

- Workflows and agents: [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Anthropic, Harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps) · [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- Frameworks: [LangChain and LangGraph 1.0](https://www.langchain.com/blog/langchain-langgraph-1dot0) · [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) · [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) · [langgraph-supervisor (archived)](https://github.com/langchain-ai/langgraph-supervisor-py)
- Multi-agent: [Anthropic research system](https://www.anthropic.com/engineering/multi-agent-research-system) · [Cognition, Multi-agents working](https://cognition.com/blog/multi-agents-working) · [Google, Scaling agent systems](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) · [MAST](https://arxiv.org/abs/2503.13657)
- Tools and MCP: [Anthropic, Writing tools for agents](https://anthropic.com/engineering/writing-tools-for-agents) · [OpenAI, Migrate to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses) · [MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) · [MCP security best practices](https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices)
- Security: [Willison on Rule of Two and adaptive attacks](https://simonw.substack.com/p/new-prompt-injection-papers-agents) · [Design patterns for securing agents](https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/)
- Evals: [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) · [Hamel Husain, LLM judges](https://hamel.dev/blog/posts/llm-judge/) · [Judge agreement study](https://arxiv.org/abs/2606.19544) · [tau-bench](https://arxiv.org/abs/2406.12045)
- Observability: [Langfuse pricing](https://langfuse.com/pricing) · [Langfuse joins ClickHouse](https://langfuse.com/blog/joining-clickhouse) · [LiteLLM security update](https://docs.litellm.ai/blog/security-update-march-2026)
- Pricing: [OpenAI pricing](https://developers.openai.com/api/docs/pricing) · [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- AWS: [App Runner availability change](https://docs.aws.amazon.com/ja_jp/apprunner/latest/dg/apprunner-availability-change.html) · [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) · [DynamoDB as a LangGraph checkpoint store](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ddb-langgraph-checkpoint.html) · [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) · [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter)
