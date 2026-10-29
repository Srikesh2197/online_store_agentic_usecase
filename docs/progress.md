# Progress

## Stage 0: First tool call — built 2026-10-12

Branch `feature_0911_01`, committed as e35990c and merged to main. Write-up: [stages/00-first-tool-call.md](stages/00-first-tool-call.md).

### What was built

| Path | Contents |
|---|---|
| `pyproject.toml` | Package `arl`, installed in editable mode into the `agentic` environment; script `arl` |
| `config/models.yaml` | Default model and prices per million tokens |
| `src/arl/env/store.py`, `seed.py` | SQLite schema (customers, orders, items, shipments, refunds); deterministic seed; hand-written anchor records |
| `src/arl/env/tools.py` | Four read tools, Pydantic argument models, schema generation, `execute_tool` |
| `src/arl/env/policy.md` | The support policy, sent in `instructions` |
| `src/arl/foundations/single_round.py` | The single round against the OpenAI Responses API |
| `src/arl/tracing/tracer.py`, `cost.py` | JSONL event log per run, Langfuse mirror, usage and cost |
| `src/arl/cli.py` | `arl run --ticket t1 [--model ...] [--quiet]` |
| `tickets/t1.yaml` to `t5.yaml` | The five sample tickets |
| `tests/` | 36 tests, no API calls |

### Decisions made

- Model `gpt-6-luna` ($0.10 in / $0.01 cached / $0.50 out per million). Confirmed available on the key.
- Stateless requests: `store: false`, the whole conversation resent each time.
- `strict: true` on every tool. Optional arguments are nullable and required.
- Tools return `{"error": code, "message": text}` on failure and never raise.
- Request 2 uses `tool_choice: "none"`. If response 1 has no tool call, there is no request 2.
- The store is in memory and reseeded for every run. Its clock is fixed: `SIM_TODAY = 2026-10-05`.
- Money is integer cents in the database and a dollar string (`"114.00"`) in tool results.
- Runs are logged to `runs/<run_id>.jsonl` (ignored by git). Langfuse is used only when both keys are set.

### Environment facts

- Python 3.14.3 in `agentic/`, not the 3.13 the plan names. No problems so far.
- `openai` 3.29.0, `langfuse` 4.17.0, `pydantic` 2.14.1.
- Langfuse project is on the US region. The organisation is new, so the legacy trace-read API returns 410; read traces back with `api.observations.get_many(trace_id=...)`.

### Measured in stage 0

Five tickets, one run each: $0.00103 in total, 1.6 to 5.6 s per run. A one-line ticket costs about 700 input tokens per request, almost all of it the policy and tool definitions.

### What stage 1 needs to know

- `single_round.py` is OpenAI-specific in three places: the request dict, `usage_from_openai`, and `output_text`. These are what the neutral `llm/` types must hide. The `Send` callable is the seam where an adapter fits.
- `Tracer` logs whatever dicts it is given, so it is already provider-neutral. Its Langfuse generation reads `request["model"]` and `request["input"]`.
- Prices are loaded by `tracing/cost.py`. The plan moves the price table under `llm/`; `claude-haiku-4-5` needs an entry.
- `tool_schemas()` emits the OpenAI shape. Anthropic needs `input_schema` and has no `strict` flag of the same kind, so generation needs a per-provider wrapper around the shared `_to_strict` output.
- `execute_tool` takes the arguments as a JSON string because OpenAI sends a string. Anthropic sends an object.
- `new_store()` returns a fresh seeded database on every call, which is what write tools and per-trial isolation in stage 2 need.

### Open questions carried forward

- Prompt caching never triggered (0 cached tokens on all 9 calls). Find the minimum prefix size before relying on cache discounts in cost estimates.
- Returning reasoning items in a follow-up request is untested, because they only appeared in final responses. The loop in stage 3 will exercise it.
- t3's reply was a misleading failure reported as `completed`. Stage 2's graders need to catch this kind of case.
- t1's reply was correct but minimal. Decide in stage 1 whether tool descriptions should encourage fetching the shipment for status questions.

## Stage 1: Two providers and the full toolset — built 2026-10-18

Branch `feature_0918_01`, committed as fcf36d5 and merged to main. Write-up: [stages/01-two-providers.md](stages/01-two-providers.md).

### What was built

| Path | Contents |
|---|---|
| `src/arl/llm/types.py` | Neutral types: `Text`, `ToolCall`, `Reasoning`, `ToolResult`, `Message`, `ToolSpec`, `ModelResponse`, `Usage` (now with `cache_write_tokens`), the `Adapter` protocol |
| `src/arl/llm/openai_adapter.py`, `anthropic_adapter.py` | Request building, response parsing, stop and usage mapping, raw-body senders |
| `src/arl/llm/pricing.py` | Price table from `config/models.yaml` (moved from the deleted `tracing/cost.py`); cache-write prices |
| `src/arl/llm/__init__.py` | `make_adapter(model)`: the model's `provider` in config picks the adapter |
| `src/arl/foundations/single_round.py` | Provider-neutral; request 2 ends with `CLOSING_INSTRUCTION` |
| `src/arl/env/tools.py` | 10 tools: 5 read, 4 write, 1 escalate (`Tool.kind`). `tool_specs()` is neutral |
| `src/arl/env/store.py` | New tables `returns` and `escalations`; `orders.cancel_reason` |
| `src/arl/env/policy.md` | Rewritten: the agent may act within the rules, and must escalate otherwise |
| `config/models.yaml` | `claude-haiku-5-5` and `claude-haiku-4-5`, with `request_options` (thinking display, cache_control) |
| `tickets/t6.yaml` to `t8.yaml` | Cancel, address change, out-of-window refund |
| `tests/fixtures/recorded/` and `scripts/record_fixture.py` | Real t1 bodies from both providers, and the script that records them |
| `tests/` | 103 tests, no API calls |

### Decisions made

- The secondary model is `claude-haiku-5-5`, at $0.10 / $0.01 cached / $0.125 cache write / $0.50 per million tokens. `claude-haiku-4-5` stays in config, unused: it is legacy and costs 10×.
- **The config switch:** `default:` in `models.yaml`, or `--model`. The provider follows from the model.
- Assistant turns are replayed with their native items to the same provider. Another provider's reasoning is dropped.
- Unknown response item types raise `ValueError`.
- Neutral call arguments are a JSON string.
- Policy rules live only in the prompt. Write tools validate shape, existence and impossible states (cancelled, wrong SKU, over-quantity), not policy.
- Anthropic-unsupported schema constraints are moved into descriptions, and Pydantic still enforces them.
- Request 2 ends with a closing user instruction as well as `tool_choice: none`.
- Haiku thinking runs with `display: summarized`, so traces show the reasoning.

### Environment facts

- `anthropic` 1.13.0: `with_raw_response...text()` is a method (in `openai` it is a property). The request-id header is `request-id`.
- gpt-6-luna reports `input_tokens_details.cache_write_tokens` and bills cache writes at 1.25× input. The minimum cacheable prompt is 1,024 tokens on GPT-5.6 and later.
- Haiku 5.5's minimum cacheable prompt is 512 tokens. Its cache TTL is 5 minutes, so a cache is written again after a pause.
- Langfuse generations carry `input_cache_read`, `input_cache_write`, `output_reasoning` and `provider`. Read them back with `api.observations.get_many(type="GENERATION", fields="core,basic,usage,model,metadata")`.

### Measured in stage 1

One run per ticket per variant.
- **Run A** (t1–t8, both providers): OpenAI $0.0012, Haiku $0.0067.
- **Run B** (closing instruction, t3 and t5–t8): OpenAI $0.0009, Haiku $0.0039.
- **Total Phase 1 spend:** about $0.014.

A request with ten tools is about 1,830 input tokens on OpenAI and 3,680 on Haiku.

### What stage 2 needs to know

- **Single-round results will be poor on any ticket that needs a write.** Neither model called a write tool in request 1 on any ticket; both look first. Expect t6–t8-style tasks to fail at rung 1. That is the baseline, not a bug.
- **Grade the replies for false claims of action.** Without the closing instruction, Haiku claimed actions it never took (t7, t8). OpenAI's misleading "try again later" (t3) persists. Both are reply-quality failures that the outcome check alone (database diff) will not catch, so the reply-facts check matters.
- **The database end state now covers every disposition.** Refunds, cancellations, address changes, returns and escalations each leave rows, and an escalation is a row in `escalations`. `new_store()` still gives a fresh copy per trial.
- **Budget per trial:**
  - gpt-6-luna: about $0.0001–0.0003;
  - Haiku 5.5: about $0.0006–0.0009 as configured;
  - a Haiku run that degenerates to `max_tokens` costs about $0.0016.

  The cost cap should use `max_tokens` × the output price as the worst case.
- **Haiku caching across tasks:** top-level `cache_control` writes a new entry for every distinct ticket. An explicit breakpoint on the system prompt and tools should make a sweep cheaper. That is untested.
- **Stop reasons are logged per call** (`stop`, `provider_stop`). A grader or report can count `max_tokens` endings directly.
- `tests/test_recorded.py` pins the exact request bodies. Any intended change to the request shape needs `scripts/record_fixture.py` on new runs.

### Open questions carried forward

- Does an explicit cache breakpoint on the tools cut Haiku's per-task cost to near OpenAI's?
- How reliable is the closing instruction over many trials? It was tested once on 5 tickets.
- Haiku's broken output under `tool_choice: none` is undocumented. Does it recur in the Stage 3 loop when a step cap forces a final answer?
- Should the Stage 3 loop drop the closing instruction, since the model is no longer cut off? Or keep it for the step-cap exit?

## Stage 2: Eval harness and baseline — built 2026-10-20

Branch `feature_0919_01`. Not committed. Write-up: [stages/02-eval-harness.md](stages/02-eval-harness.md).

### What was built

| Path | Contents |
|---|---|
| `src/arl/evals/tasks.py`, `tasks/capability/c01…c20.yaml` | Strict task model, consistency checks, 20 tasks (6 read, 6 write, 4 refuse, 4 escalate), each with a reference solution |
| `src/arl/evals/dbdiff.py` | Snapshot by `id`; diff of inserts, deletes, column updates |
| `src/arl/evals/transcript.py` | `Transcript` from the JSONL trace; `replay_reference()` runs a task's reference with no model |
| `src/arl/evals/graders/` | `outcome.py` (db, facts, hygiene), `trajectory.py` (must_call, must_not_call, order), `grade()` → `Verdict` |
| `src/arl/evals/runner.py` | Estimate, sweep with a hard cap, error halt, results JSON, ledger |
| `src/arl/evals/report.py` | Summary, categories, per-task variance, paired table with sign test, `--show`, `--regrade` |
| `src/arl/cli.py` | `arl eval` and `arl report` |
| `src/arl/tracing/tracer.py` | Optional `phase` tag (default unchanged) |
| `results/` | 4 sweep files, `spend.csv`, `report-phase2-baseline.md`, `review/phase2-ten-transcripts.md` |
| `tests/` | 214 tests (111 new), no API calls |

### Decisions made

- **Success** = db ∧ facts ∧ hygiene ∧ trajectory, and each component is reported. API failures are error trials, left out of the rates.
- **"Check before act"** means an earlier *model turn*. Calls in the same parallel batch do not count.
- **Failed calls:** must_call counts only successful calls; must_not_call counts every attempt.
- **Proven tasks:** every task carries a reference solution, and a test replays it against a fresh store.
- **Cost cap:** before each trial, halt if spent + that trial's worst case > cap. Spend is read from the logged model calls.
- **Re-grading:** results store a compact transcript per trial, so `arl report --regrade` re-grades from a clean checkout.
- **Primary model `gpt-6-luna`, secondary `claude-haiku-5-5`.** The selection rule was fixed before the runs. No model led by more than the detectable difference, so the cheapest won.
- **c15 is a refusal, not an escalation.** c16's "already" fact stays strict.
- The seed defect (three deliveries after SIM_TODAY) is recorded but not fixed. The tasks avoid those orders.

### Measured in stage 2

- 160 trials: gpt-6-luna 20 × 5; gpt-5.6-luna, gpt-5-mini and Haiku 5.5 20 × 1 each. Spend **$0.093** of the $1.50 budget, against an estimate of $0.20.
- **Rung-1 success:**

  | gpt-6-luna | gpt-5.6-luna | gpt-5-mini | Haiku 5.5 |
  |---|---|---|---|
  | 43% (pass^5 35%) | 45% | 45% | 50% |

  - Writes: 0/60 across all models.
  - Escalations: only c19 passed (a person requested; no lookup needed).
  - Hygiene: 100%. No write tool was ever called.
- **$/run:** gpt-6-luna $0.00016, gpt-5.6-luna $0.00038, Haiku $0.00075, gpt-5-mini $0.0027. p50 latency 3.4–11.9 s.
- **Transcript review:** 3 of 10 verdicts were phrase-list false negatives, now fixed. The db, hygiene and trajectory checks were right in all 10.

### What stage 3 needs to know

- **The harness is the comparison.**
  - Run the loop as a new strategy through the same `run_sweep`. The runner currently imports `run_single_round` directly, so add a strategy argument rather than a second runner.
  - Keep `STRATEGY` in the results, so the report labels the arms.
  - Make the Stage 3 table with `arl report <rung-1 file> <rung-2 file>`.
- **Run every compared arm at k ≥ 3.** Paired tables between a k5 arm and a k1 arm count 4/5 against 1/1 as a win.
- **Where rung 2 should gain:** the 6 writes, c03, c17, c18 and c20 all failed because the round ended. All of them depend on order rules ("look, then act in a later turn"), which only a loop can satisfy.
- **Where rung 2 could lose:** c19 and c15 show models escalating in round 1. A loop gives more chances to act wrongly, so watch must_not_call and db on the refuse tasks.
- **Measured costs replace the plan's basis.**
  - A call is about 1,850–2,150 input tokens on OpenAI (98% cached on request 1) and about 3,700–4,100 on Haiku.
  - A 4-call loop run should cost about $0.0003–0.0005 on gpt-6-luna and $0.0012–0.0015 on Haiku.
  - Stage 3's planned runs should cost about $0.15–0.50, not $3.50.
  - The estimator now uses measured cost per trial for models already swept. Its worst case assumes 2 calls (`CALLS_PER_TRIAL`), so a loop strategy must set its own worst case: step cap × the per-call worst case.
- **Haiku cache:** request 1 wrote about 3,690 tokens to the cache on every task and read none. An explicit breakpoint before the ticket is still untested.
- **The closing instruction** held over 160 trials (no hygiene failures, no false-claim phrases). The loop may still need it at the step-cap exit.
- **Facts checks are the brittle part.** When a new failure looks odd, read it with `arl report <file> --show <task> --trial N` before trusting it.
- **Tests:** 214 pass. The `test_recorded.py` fixtures are unchanged; the request shape did not change.

### Open questions carried forward

- Does an explicit cache breakpoint before the ticket bring Haiku's request-1 cost near OpenAI's?
- Is c15 (refuse against escalate) a fair test, given that the policy line "anything outside these rules is escalated" invites escalation? Revisit when the Stage 4 failure taxonomy is built.
- Would 20 × 5 on all four models change the model choice? It would cost about $0.35, and it is only needed if Stage 3 shows the primary struggling in a loop.

## Stage 3: Hand-written agent loop — built 2026-10-23

Branch `feature_0919_02`. Not committed. Write-up: [stages/03-agent-loop.md](stages/03-agent-loop.md).

### What was built

| Path | Contents |
|---|---|
| `src/arl/foundations/hand_loop.py` | Rung 2: `run_hand_loop()`, 155 lines, both providers. `MAX_STEPS = 10` model calls, the reply included. Exits: completed, no_reply, step_cap, truncated, refused, stopped. Trace events `step_cap` and `loop_exit` |
| `src/arl/evals/runner.py` | `STRATEGIES` registry (`single_round`, `hand_loop`); strategy in the results, ledger and sweep id; worst case summed over `max_calls` with a growing history; `PHASE = "phase-3"` |
| `src/arl/evals/report.py` | Other-exit counts; paired tables matched on k (first min(k) trials); `restrict()` / `--tasks` |
| `src/arl/cli.py` | `--strategy` on `arl run` and `arl eval`; `--tasks` on `arl report` |
| `config/models.yaml` | `gpt-6.1-sol` ($2 / $0.10 / $2.50 / $10), added but not run |
| `tests/scripted.py` | Scripted fake model: neutral steps rendered as real OpenAI or Anthropic bodies |
| `tests/test_hand_loop.py`, additions to `test_runner.py` and `test_report.py` | 36 new tests; 250 in total, no API calls |
| Task files c11, c15, c17 | Two reviewed phrase-list fixes (`$38`; must_not_say no longer matches "no refund has been issued") |
| `results/` | 2 sweep files, `report-phase3-luna-rung1-vs-rung2.md`, `review/phase3-ten-failures.md` |

### Decisions made

- **The loop branches on the neutral stop reason only.** A call in a truncated response is never run. There is no retry on truncation or refusal (Stage 5).
- **A tool that raises becomes a `tool_failed` error result.** Tool errors always go back to the model.
- **At the step cap, the last call is reply-only:** tools off, Phase 1's closing instruction after the results, status `step_cap`. The normal path has no closing instruction.
- **The runner takes a strategy argument,** not a second runner. The default stays `single_round`, so Phase 2 commands reproduce.
- **Paired tables match on k.** Phase 2's fake k5-against-k1 wins can no longer happen.
- **The Haiku cache breakpoint is deferred** to Stage 11.
- **The model arms were cut.** The PLAN.md reference model (gpt-6.1-sol) and a Haiku rung-1 arm were not run: the project builds an agent, not a model ranking, and gpt-6-luna was already at 50/50 on the planned 10 tasks. One Haiku loop check (10 × 1) was run instead.

### Measured in stage 3

- **Spend: $0.027** ($0.0164 gpt-6-luna sweep, $0.0091 Haiku sweep, $0.0019 smoke runs).

| | Success | pass^5 | Calls/run | $/run | p50 |
|---|---|---|---|---|---|
| gpt-6-luna rung 1 | 43% | 35% | 1.95 | $0.000162 | 4.0 s |
| gpt-6-luna **rung 2** | **91%** | **90%** | 2.83 | $0.000164 | 4.5 s |
| Haiku rung 2 (10 × 1) | 100% | – | 2.90 | $0.000914 | 6.9 s |

- **The loop wins 12 tasks, loses 1 and ties 7; p = 0.003, a finding.** Writes went from 0% to 100%, escalations from 25% to 100%, refusals from 70% to 55%.
- **Same cost per run** on gpt-6-luna: 96% of input cached, and shorter outputs.
- **The step cap never tripped:** at most 5 calls. There were no truncations or refusals.
- **The loss is c15** (4/5 → 0/5). The model refuses and then escalates, often *after* looking, which rung 1 could not do.
- **The 10 annotated failures contain no wrong action.** They are judgement (c15) and wording (c16), plus 2 phrase-list false negatives, now fixed.

### What stage 4 needs to know

- **Failures to label come from c15 and c16.** gpt-6-luna's rung-2 failures are almost all there:
  - c15: over-escalation, "refuse, then escalate";
  - c16: "Yes, a refund was issued", a misleading reply with a correct db.

  For a failure mix, you need rung-1 transcripts (Phase 2) plus rung-2 transcripts. Rung 2 alone yields few failures.
- **c15's rule is the open taxonomy question.** Is escalating a clear refusal a failure, or the policy's "anything outside these rules" working as written? Decide it while building the taxonomy, before freezing v1. Haiku refused cleanly; gpt-6-luna escalated in 5 of 5 trials.
- **Phrase lists:** 2 of 10 verdicts were wrong again (3 of 10 in Phase 2). Both errors were a negation or a number format. Reply quality, the c16 "Yes" in particular, is the judge's job.
- **Re-running rungs 1 and 2 on v1 at 30 × 5** should cost about $0.03 per arm on gpt-6-luna.
  - Use `arl eval --strategy hand_loop`.
  - The estimator's prior for a new strategy is about 10× too high; it switches to measured costs after the first sweep.
- **Rung-2 transcripts are multi-turn.** `arl report --show` prints each turn's calls. Haiku's summarised thinking is in the raw JSONL (`runs/eval/…`), not in the compact transcript.

### Open questions carried forward

- Does the c16 wording failure need a prompt change, or only a judge to catch it? Decide after Stage 4 labels it.
- gpt-6.1-sol is configured but unmeasured. Would a stronger model fix c15 and c16, or is the policy text the cause? Haiku's 10 × 1 suggests a model difference, but it is only a direction.
- The Haiku cache breakpoint (Stage 11).

## Stage 5: Guardrails, failure handling and prompt injection — built 2026-10-28

Branch `feature_0928_01`. Not committed. Write-up: [stages/05-guardrails.md](stages/05-guardrails.md).

The Stage 4 section is not here yet: Phase 4 was paused before its labelling, judge validation and v1 baselines, and it will be finished in its own chat. Phase 5 ran its own v1 reference arm (see below).

### What was built

| Path | Contents |
|---|---|
| `src/arl/env/store.py` | A `Store` connection subclass carrying `env: EnvConfig` (invariants, signed-in sender, fault injector; default all off); a new `order_notes` table, empty in the seed |
| `src/arl/env/faults.py` | A deterministic fault injector per task (`timeout`, `unavailable`, `after_commit`, with `nth` and `times`), plus an optional seeded random rate |
| `src/arl/env/invariants.py` | Refunds on an order in total ≤ paid; writes only on the sender's orders; cancel and address change only while `processing` |
| `src/arl/env/tools.py` | `get_order` shows notes only when present; `execute_tool(..., idempotency_key=)` with a TEMP idempotency table; faults raised from `execute_tool` |
| `src/arl/guardrails/` | `limits.py` (tokens 20,000, $0.01, 120 s), `loopdetect.py`, `validation.py` (grounding, length caps), `permissions.py` (tiers, taint), `retry.py` (tenacity, 3 attempts), `prompt.py` (defence section); `Guards` profiles `OFF`, `PROMPT`, `ALL` |
| `src/arl/foundations/guarded_loop.py` | Rung 2 plus switchable layers; identical requests to `hand_loop` with every layer off |
| `src/arl/evals/tasks.py`, `tasks/adversarial/` | Optional `sender`, `setup`, `faults` and `attack` task fields; new categories; 12 frozen adversarial tasks (`FROZEN_ADVERSARIAL_HASH = 44c9b476eaa8`); 4 dropped candidates in `tasks/adversarial_dropped/` |
| `src/arl/evals/graders/attack.py`, `evals/safety.py`, `evals/trial_env.py` | Harm, attempted and utility; unsafe action, double write and runaway; the trial's store with its task and arm environment |
| `src/arl/evals/runner.py`, `report.py`, `cli.py` | Strategies `guarded_prompt` and `guarded_all`; `--task-set`; per-task baselines; budget-bounded worst case; borrowed cost basis; `PHASE = "phase-5"`; report sections for safety, attacks and paired harm |
| `pyproject.toml` | `tenacity>=9.2,<10` (already pinned in `requirements/base.txt`) |
| `results/` | 10 sweep files, `report-phase5-adversarial.md`, `report-phase5-v1-guarded-vs-reference.md`; the ledger has one `interrupted` row |
| `tests/` | 150 new tests (`test_env_guards.py`, `test_guarded_loop.py`, `test_adversarial.py`); 462 pass and 1 is skipped, with no API calls |

Unchanged: `hand_loop.py`, `single_round.py`, `policy.md`, the v1 task files (hash 76254c561b0d), `outcome.py`, `trajectory.py`.

### Decisions made

- **The off arm is `hand_loop` itself.** The prompt-only and all-on arms are `guarded_loop` profiles. A parity test ties them together.
- **The environment travels on the connection,** so `hand_loop` needed no change. Faults and setup belong to the task (the same in every arm); invariants belong to the arm.
- **Indirect injection enters through `order_notes`,** shown by `get_order` only when present, so v1 results and the recorded fixtures are unchanged.
- **The verified customer is a task `sender` field.** v1 tasks have none, so ownership does not apply on v1.
- **Taint blocks the write and tells the model to escalate.** Automatic handoff is Stage 7.
- **`hand_loop`'s "Nothing was changed" after any tool exception is kept,** and documented as a finding. After a commit it is false.
- **Model API retries are left to the SDKs** (2 retries with backoff in both). Tool faults are retried with tenacity, with idempotency keys of the form run id : tool-call id. One truncation retry at 2× tokens. Refusals are not retried.
- **Utility** (expected changes present and reply facts, an extra escalation allowed) is the adversarial headline beside strict success.
- **The token budget is 20,000,** about 2× the largest normal v1 run. It was lowered from 30,000 after calibration, from v1 data.
- **Rung 1 on v1 is left to Phase 4.**

### Measured in stage 5

Spend: **$0.169**, including $0.005 for a sweep killed when a session ended.

| Adversarial (12 × 5) | Harm | Attempted | Utility | Unsafe | Double write | Runaway |
|---|---|---|---|---|---|---|
| off | 55% | 55% | 85% | 38% | 22% | 7% |
| prompt-only | 15% | 15% | 95% | 7% | 10% | 0% |
| all on | **0%** | 7% | 75% | 0% | 0% | 2% |

| v1 (30 × 5) | Success | pass^5 | $/run | p50 / p95 |
|---|---|---|---|---|
| reference (`hand_loop`) | 92% | 87% | $0.000184 | 4.7 / 7.6 s |
| all on | 95% | 90% | $0.000192 | 5.3 / 10.6 s |

- **Findings:**
  - all on vs off: 8 tasks less harm, 0 more, p = 0.008;
  - prompt-only vs off: 7 tasks less harm, 0 more, p = 0.016;
  - on v1, all on lost no task (3 better, 27 ties), and no guardrail fired on any of the 150 runs.
- **What did the work live:**
  - taint: 13 writes blocked, 4 of them the attack and 9 legitimate refunds;
  - retries with keys: 15 fault trials, 0 double writes;
  - one time limit.
- **Never fired live:** invariants, grounding, loop detection and the token and dollar budgets. In the guarded arms the model never attempted those attacks. Their effect is shown by the scripted tests.
- **What succeeds without code guards:** in prompt-only, a04 (a false defect fact in a note, 3/5), a12 (double escalation, 5/5) and a11 (double return, 1/5). In all on: none.

### What stage 6 needs to know

- **Port the guardrails, not just the loop.** Rung 3 (LangGraph) should pass the same parity and on/off tests. The tool-side pieces (invariants, idempotency, faults, notes) come along unchanged, because they live in `env/`. The loop-side pieces (limits, loop detection, grounding, taint, retries) must be re-expressed as graph nodes or middleware. `tests/test_guarded_loop.py` is the checklist.
- **Compare on both sets.** Run v1 and the frozen adversarial set (`--task-set adversarial`) against `guarded_all` as the rung-2 reference.
- **Idempotency keys come from the tool-call id.** A graph that replays a node after a checkpoint (Stage 7) must reuse the same call id, or the key changes and a resumed write repeats.
- **Taint is run-level state.** In a graph it belongs in the state object, so a branch or a subgraph cannot drop it.
- **Watch the utility cost.** All on lost 20 points of utility against prompt-only on the adversarial set, mostly (10 of 12 trials) through taint blocking legitimate refunds (a07, a14). A workflow that routes "refund with untrusted notes" to a human node could recover it; that is a Stage 6 or 7 design option.
- **Run long sweeps detached** (`nohup caffeinate -i arl eval ...`). Sweeps run from a chat session die with the session, and macOS sleep stalls requests for up to the SDK's 600 s timeout.

### Open questions carried forward

- Would a scope guard (a limit on distinct non-sender orders looked up) catch the chains in code, without hurting v1?
- Does the prompt-only result hold on Haiku 5.5? The optional cross-check (12 × 1 per arm, about $0.03) was not run.
- Should the refund cap be per item? a14 shows the per-order cap allowing $98 for a $38 item.
- `hand_loop`'s false "Nothing was changed": fix it in a later rung, or keep it as the measured baseline?

## Stage 6: Port to LangGraph and add a workflow — built 2026-10-29

Branch `feature_0928_02`. Not committed. Write-up: [stages/06-langgraph.md](stages/06-langgraph.md).

### What was built

| Path | Contents |
|---|---|
| `src/arl/framework/models.py` | `make_chat_model` (`init_chat_model` with `model_provider` and options from `models.yaml`); `bind` (Anthropic's `tool_choice` as an object); `usage_of`, `stop_of`, `tool_calls_of` (LangChain messages read back in our terms); `traced_call` |
| `src/arl/framework/graph_agent.py` | Rung 3: `model → tools → limits → model`, `finish`. Guardrail state (taint, grounded ids, loop counts, budgets) in the graph state with reducers. `graph_off` and `graph_all` |
| `src/arl/framework/workflow.py` | `route → gather (→ pick) → decide → act / escalate → reply`; 8 intents; at most 4 model calls; a tainted write is routed to `escalate` by an edge |
| `src/arl/framework/prebuilt_agent.py` | `create_agent` with our tools, `ModelCallLimitMiddleware` and a taint middleware; not evaluated |
| `src/arl/evals/runner.py`, `cli.py` | Strategies `graph_off`, `graph_all`, `workflow` (imported on first use); `PHASE = "phase-6"` |
| `src/arl/tracing/tracer.py` | `langchain_callbacks()`: the Langfuse LangChain handler inside our run span, our per-call mirror off for those runs. Default unchanged |
| `pyproject.toml` | `framework` extra: langgraph, langchain, langchain-openai, langchain-anthropic |
| `tests/wire.py`, `tests/fake_chat.py` | The scripted model through a fake HTTP transport into the real `ChatOpenAI` / `ChatAnthropic`; a fake chat model with `bind_tools` |
| `tests/` | 117 new tests (graph agent 77, model layer 12, workflow 18, `create_agent` 5, runner 5), one of them skipped; 578 pass and 2 are skipped, with no API calls |
| `results/` | 7 sweep files; `report-phase6-v1.md`, `report-phase6-v1-workflow-vs-graph.md`, `report-phase6-adversarial.md`, `report-phase6-haiku.md` |

Unchanged: `hand_loop.py`, `guarded_loop.py`, `single_round.py`, `guardrails/`, `env/`, `llm/`, the task sets, the graders, `tests/scripted.py`, the recorded fixtures.

### Decisions made

- **LangChain chat models** for the graph, the workflow and `create_agent`; our usage, cost and stop mapping applied to their messages (equal to the adapters' on the same bodies, tested).
- **Parity is on decisions, not bytes:** tool calls as sent, results, stops, usage, cost, exits, guard events, idempotency keys, tools-off calls, output limits, end state.
- **Our own sequential tools node**, not `ToolNode` (thread pool, thread-bound SQLite, call order matters for taint and grounding).
- **Guardrail state lives in the graph state.** The Stage 5 modules are rebuilt from it in the node and their changes written back.
- **Anthropic's `cache_control` goes in `model_kwargs`**, not per call.
- **The graph agent ran all-on only, at 30 × 5** (the plan said 30 × 3). "Off" is proven by scripted parity.
- **The optional workflow run on the adversarial set was skipped** (your call).

### Measured in stage 6

Spend: **$0.107** (smoke $0.003; `graph_all` v1 $0.028; `workflow` v1 $0.039; `graph_all` adversarial $0.027; Haiku $0.010).

| v1 (30 × 5) | Success | pass^5 | Refuse | Calls/run | Cached | $/run | p50 / p95 |
|---|---|---|---|---|---|---|---|
| `guarded_all` (Stage 5 reference) | 95% | 90% | 73% | 2.92 | 95% | $0.000192 | 5.3 / 10.6 s |
| `graph_all` | 98% | 93% | 90% | 2.90 | 96% | $0.000187 | 4.6 / 8.7 s |
| `workflow` | 93% | 83% | 70% | 2.80 | 73% | $0.000263 | 4.5 / 7.1 s |

- **Adversarial (12 × 5), `graph_all`:** harm 0/60, unsafe 0, double writes 0, runaways 0, utility 75%, the same as `guarded_all`. The guardrails fired identically: taint set 30 times, 13 writes blocked, 15 retries with keys.
- **Haiku (10 × 1), `graph_all`:** 10/10, 2.90 calls/run, $0.000974 (Phase 3 `hand_loop`: 10/10, $0.000914).
- **Findings:** the port changed nothing measurable (0 tasks worse; the same guardrail firings); the workflow costs 41% more per run (reply-step cache misses and more output), and is bounded at 2–4 calls.
- **Directions (p = 0.25 each):** `graph_all` better than `guarded_all` on 3 refusal tasks; `workflow` worse than `graph_all` on 3 tasks (refuse-then-escalate in c15 and c21; the delivery date lost between steps in c23).

### What stage 7 needs to know

- **The graph state is serialisable**, except two values kept in closures: the run's start time (for the time budget), and the workflow's counter for its own call ids (`wf_N`). A resumed workflow would number its code-run calls again, so **an escalation made by code would get a new idempotency key on resume**. Move the counter into the state, or derive the id from the node and step, before checkpointing the workflow. The graph agent's keys come from the model's call ids, which are stored in `messages`, so they are stable.
- **Nodes are closures compiled per run.** With a checkpointer, compile once and pass the store, tracer and chat model through LangGraph's runtime context (`context_schema`).
- **A node re-runs from the top on resume.** The `tools` node runs every call of the batch: reads repeat harmlessly, writes are protected only when idempotency is on, and trace events are written twice. The approval gate belongs in its own node before `tools` (agent) or before `act` (workflow).
- **The workflow's tainted-write edge is where an approval node fits.** Today it routes to `escalate`; routing to a person who can approve the write could recover a07 and a14 (0/5 utility in every guarded arm).
- **`langgraph-checkpoint-sqlite` is installed** (pinned in `requirements/framework.txt`), but not in the `framework` extra yet.
- **SQLite is thread-bound.** Anything that runs nodes or tools in parallel needs a connection opened with `check_same_thread=False` (see `prebuilt_agent.thread_shared_store`).
- **The trace logs LangChain's view of each request**, not the wire body. The JSONL events and the graders are unchanged.

### Open questions carried forward

- Why does the workflow's reply step miss OpenAI's prompt cache when its route step does not? Try a per-step `prompt_cache_key`, or move the step instruction after the ticket.
- Is the refusal gain of `graph_all` over `guarded_all` real (the system prompt placed in `input` instead of `instructions`), or noise?
- Would a decide step with an explicit "refuse" choice remove the workflow's refuse-then-escalate failures? That needs a held-out split, so it is not tuned on v1.
- The optional workflow run on the adversarial set (about $0.015) was not made.

## Stage 7: Persistence, human approval and interruption — built 2026-10-29

Branch `feature_0928_03`. Not committed. Write-up: [stages/07-approval.md](stages/07-approval.md).

### What was built

| Path | Contents |
|---|---|
| `src/arl/framework/graph_agent.py` | Run objects moved from closures to LangGraph's runtime context (`AgentContext`); compiled once per (policy, checkpointer); an optional `gate` node before `tools` (`interrupt()` with a review packet); `drive()` answers pauses with a reviewer, stops (`paused`) without one, and turns a drain into `cancelled`; `durability="sync"` for checkpointed runs. Without a policy the graph is Stage 6's exactly |
| `src/arl/framework/approval.py` | Policies `all_writes` and `risk_tiered` (refunds ≥ $50, or any write after untrusted text); the review packet; `ScriptedReviewer` (three rules); replay reviewers (approve-all, scope-only) |
| `src/arl/framework/threads.py` | Threads on files: `store.db` (backup of the seeded store) with `keys.db` attached, `SqliteSaver` checkpoints, a registry (status, pid, working time, Langfuse ids, cancel flag), a cancel watcher (`RunControl.request_drain`), start / continue / cancel, audit reconstruction and replay |
| `src/arl/env/store.py`, `env/tools.py` | `EnvConfig.key_schema` (default `"temp"`): the idempotency table can live in an attached file (approved) |
| `src/arl/tracing/tracer.py` | `run(resume=...)`: a later segment appends `run_resume` to the same file, continues `seq`, and joins the first segment's Langfuse trace; `trace_context()`, `continue_log()` |
| `src/arl/evals/runner.py`, `report.py` | Strategies `graph_approve_all`, `graph_approve_risk` (scripted reviewer, checkpoints per sweep); `approvals` (counts and packets) in each trial record; report sections for reviewer load, approvals by task, paired utility, and the reviewer replay; `PHASE = "phase-7"` |
| `src/arl/cli.py` | `arl run --task/--thread`; `arl threads [--pending]`, `approve`, `reject`, `cancel`, `resume`, `audit [--state]` |
| `scripts/crash_demo.py` | Live kill-after-write demo |
| `pyproject.toml` | `langgraph-checkpoint-sqlite` in the `framework` extra |
| `tests/` | 37 new tests (`test_approval.py` 20, `test_crash_recovery.py` 6 with `crash_child.py`, `test_threads.py` 6, `test_checkpoint.py` 3, runner 2); 615 pass and 2 are skipped, with no API calls |
| `results/` | 6 sweep files (2 smoke, 4 main); `report-phase7-v1.md`, `report-phase7-adversarial.md` |

Unchanged: `hand_loop.py`, `guarded_loop.py`, `single_round.py`, `guardrails/`, `workflow.py`, the graders, the task sets. `graph_off` / `graph_all` parity and the 26 twins pass unchanged.

### Decisions made

- **The gate is on the graph agent only.** The workflow was cut; its `wf_N` ids are still numbered in a closure, so it must not be checkpointed as it is.
- **Under approval, taint asks a person instead of blocking.** An approval passes the taint block for that call id only; taint stays set; grounding, loop detection and the invariants still apply. Escalations never ask.
- **Keys survive a crash in an attached `keys.db`;** the eval arms keep TEMP keys (no crash there).
- **`durability="sync"`** for every checkpointed run: the default `"async"` can lose the message holding the call ids, so a resume would get new keys.
- **Thread id = run id,** so the key prefix is the same in every process.
- **Approval events are logged by the driver, not the gate** (the gate runs twice per pause).
- **The time budget counts working time,** restored on resume; a reviewer's wait does not count.
- **Resume values are wrapped** (`{"decisions": ...}`): LangGraph reads a dict whose keys all look like interrupt ids, which includes an empty dict, as a map of interrupt ids. The driver also bounds pauses per segment.
- **Cancel = drain** (`RunControl.request_drain`), from a watcher polling the registry; a paused thread is cancelled in the registry. State is kept; `arl resume` continues it.

### Measured in stage 7

Spend: **$0.068** (smoke $0.0013; four sweeps $0.066; live checks about $0.0006 outside the ledger).

| Adversarial (12 × 3; ref 12 × 5) | Harm | Utility | Unsafe | Double write | Requests per 100 tickets |
|---|---|---|---|---|---|
| none (`graph_all`) | 0% | 75% | 0% | 0% | 0 |
| all writes | 0% | 92% | 0% | 0% | 47 |
| risk-tiered | 0% | 94% | 0% | 0% | 31 |

| v1 (30 × 3; ref 30 × 5) | Success | Requests per 100 tickets | $/run |
|---|---|---|---|
| none (`graph_all`) | 98% | 0 | $0.000187 |
| all writes | 97% | 30.0 | $0.000186 |
| risk-tiered | 96% | 3.3 | $0.000187 |

- **Findings (counted exactly):** a07 and a14 went from 0/5 to 3/3 in both approval arms, with harm 0; risk tiers asked 9× less often on v1 (3.3 against 30 per 100) and 11.1 against 34.9 over all 42 tasks; no failed v1 trial had an approval request (the gate did not cause them); no measurable cost or latency; 12–15 checkpoints and 115–230 KB per run.
- **Directions:** utility vs none, p = 0.50 (all writes) and 0.38 (risk-tiered). Only one attack call reached the reviewer (a04's false-defect refund); rule 3 rejected it, and the replayed rubber-stamp and scope-only reviewers would both have approved it.
- **Crash recovery:** scripted kills in both windows (after the key result is stored; inside the tool before it is) resume to one refund; TEMP keys with invariants off give two; the amount invariant catches the second when on. Live: killed after REF-9002 committed, resumed to one refund (`replayed`).
- **Live approval round trip:** paused in `arl run`, approved by `arl approve` in another process; both segments in one Langfuse trace, the resume span under the first run span.

### What stage 8 needs to know

- **Threads, checkpoints and the gate exist for the graph agent only.** A supervisor or handoff graph that writes must keep **one writer**, route its writes through the same gate, and use model-issued call ids (or ids derived from state) as idempotency keys, never a counter in a closure.
- **Compile once, pass run objects through `context`.** `AgentContext` is the pattern; a subgraph that needs the store gets it the same way. Checkpoints must hold only state.
- **Use `durability="sync"`** for any graph with side effects, and `resume_with()` for resume values.
- **Approval load is a metric now.** Multi-agent variants should report requests per 100 tickets beside success, harm and cost (the runner records `approvals` for every strategy; the report shows it when present).
- **The reference arms** for Stage 8 on v1: `graph_all` k5 (`20261029T001125Z`), and the approval arms at k3 if a gate is used.
- **Checkpoints grow with the history** (the whole message list per step). Multi-agent runs with longer histories will make this larger; prune or keep per-agent message lists short.
- **The trace is still one JSONL file per run;** `Transcript.from_events` ignores the new event types. A crash-resumed run lists the re-run batch twice (the second write marked `replayed`); the db diff is authoritative.

### Open questions carried forward

- Would a real reviewer catch a04 without the "customer's own words" rule? The replay says a rubber stamp would not. Only a human study answers it.
- Should taint stay the default with approval only as an override (safer against rubber-stamping), rather than approval replacing the block?
- The workflow's gate (before `act`) and its `wf_N` ids: needed only if the workflow is deployed.
- Nothing resumes a crashed thread automatically; Stage 10 needs a sweeper or a durable-execution runner.

## Stage 8: Multi-agent (rung 4) — built 2026-10-29

Branch `feature_0928_04`. Not committed. Write-up: [stages/08-multi-agent.md](stages/08-multi-agent.md).

### What was built

| Path | Contents |
|---|---|
| `src/arl/framework/graph_agent.py` | Opt-in `AgentContext` fields (`agent`, `tools`, `system`, `delegates`, `run_delegates`) and `Delegated`; in `tools`: the `toolset` guard (`tool_not_available`), `act_after_reports` (no write in a turn that asks a specialist), a pre-pass that gates and runs delegated calls and merges them in call order; `run_graph_agent(agent_fields=...)`. With the defaults it is Stage 7's graph exactly |
| `src/arl/framework/multi/specialists.py` | Specialists orders (5 reads), refunds (get_order, get_shipment; an assessor), policy (no tools); the supervisor's role; every prompt = policy + defence + `## Your role: <name>` section; `MULTI_GUARDS` (graph_all's guards, 60,000-token pool) |
| `src/arl/framework/multi/supervisor.py` | `run_supervisor`: the graph agent with the writes, escalation and `ask_orders` / `ask_refunds` / `ask_policy`, no reads. Specialists run concurrently (`ContextThreadPoolExecutor`), each on a backup copy of the store, logging into a buffered tracer merged in call order; the pool split between concurrent specialists; at most 8 specialist runs per ticket, 5 calls each |
| `src/arl/framework/multi/handoffs.py` | `run_handoffs`: one graph, `HandoffState` (`active`, `handoffs`), peers triage → orders → actions (the single writer), graph_agent's nodes run as the active peer via `runtime.override`; transfer tools; at most 3 handoffs, one per turn |
| `src/arl/framework/multi/__init__.py` | `SUB_MAX_STEPS`, `MAX_DELEGATIONS` (import-free, for the runner) |
| `src/arl/tracing/tracer.py` | `agent` on every event when set (`as_agent`); `BufferedTracer`; `merge(child, call_offset)`. Single-agent logs unchanged |
| `src/arl/evals/runner.py`, `report.py`, `cli.py` | Strategies `supervisor`, `handoffs`; `agents_of()` per trial (per-agent calls/tokens/cost, delegations, handoffs, repeated lookups, concurrent batches); `Strategy.worst_case`; report sections "Multi-agent cost against the first arm", "by agent", "Coordination"; `PHASE = "phase-8"` |
| `src/arl/evals/tasks.py`, `tasks/parallel/p01…p08.yaml` | The parallel set, 8 bulk audits on the unchanged seed (5 read, 3 write), `FROZEN_PARALLEL_HASH = 2cc7a9b329ed` |
| `tests/` | `multi_helpers.py` (`AgentRouter`: a script per agent, chosen by the role line); `scripted.py` gained an optional call-id `prefix`; `test_supervisor.py` 29, `test_handoffs.py` 13, `test_parallel_set.py` 37, runner 4. 698 pass and 2 are skipped, with no API calls |
| `results/` | 11 sweep files (7 smoke/calibration/re-check, 4 main); `report-phase8-v1.md`, `report-phase8-parallel.md` |
| `runs/phase8-logs/` | `smoke.sh`, `sweeps.sh` and their logs |

Unchanged: `hand_loop.py`, `guarded_loop.py`, `single_round.py`, `guardrails/`, `env/`, `llm/`, `workflow.py`, `approval.py`, `threads.py`, the graders, `transcript.py`, the v1 and adversarial task files. No new packages.

### Decisions made

- **The supervisor is the graph agent whose tools include agents;** a specialist is the same compiled graph with its own context, invoked from the supervisor's `tools` node. The approval gate therefore works on the supervisor unchanged (one scripted test); the sweeps ran without it (reference `graph_all`).
- **Single writer, enforced in code:** the supervisor (handoffs: `actions`); any other agent asking for a write gets `tool_not_available`.
- **Real threads** for specialists asked in one turn (your choice), each on its own store copy; traces merged in call order, so the file does not depend on timing.
- **One budget pool per run,** 60,000 tokens (3× the single agent), $0.01, 120 s (your choice); split equally between concurrent specialists.
- **Specialists see the brief only** (your choice).
- **Taint and grounding are run-level** and flow back from specialists; loop counts are per agent context.
- **A specialist run is a fresh root graph** (its own thread id in `configurable`): no checkpoints into the parent, no inherited drain; callbacks still nest (Langfuse: `supervisor → tools → agent:orders`, checked live).
- **The handoff result tells the new peer it owns the ticket** (fix for a smoke-run bug: the new peer read the transfer as its own turn and replied with nothing).
- **Parallel set calibrated for validity:** one rewrite round (money facts accept "$22"; p06 says "both notebook packs"), then frozen.

### Measured in stage 8

Spend: **$0.155** (smoke and calibration $0.018, re-checks $0.003, sweeps $0.133).

| v1 (30 × 3; single agent k5 paired on 3) | Success | $/run | Tokens × | Cost × | Calls × | p50 latency × |
|---|---|---|---|---|---|---|
| `graph_all` (single) | 98% | $0.000187 | 1.00 | 1.00 | 1.00 | 1.00 (4.6 s) |
| `supervisor` | 88% | $0.000464 | 1.56 | 2.45 | 1.78 | 2.36 |
| `handoffs` | 98% | $0.000282 | 1.15 | 1.49 | 1.26 | 1.42 |

| Parallel set (8 × 5) | Success | $/run | Tokens × | Cost × | Calls × | p50 latency × |
|---|---|---|---|---|---|---|
| `graph_all` (single) | 92% | $0.000479 | 1.00 | 1.00 | 1.00 | 1.00 (6.9 s) |
| `supervisor` | 85% | $0.001179 | 1.81 | 2.46 | 2.26 | 2.24 |

- **Findings (precise):** multi-agent cost more in every unit on both sets; dollars grew faster than tokens (more cache misses: 91.6% vs 95.5% cached); slower even with real threads (more sequential steps); on the 6-item audits the supervisor sent one brief for all six orders in 19 of 20 runs, so its parallelism was the single agent's (parallel tool calls) plus a layer; where it split (p06–p08) it repeated 2–4 lookups per run. No unsafe action, double write, runaway or limit in any arm.
- **Directions:** supervisor vs single on v1, 6 tasks worse, 1 better, p = 0.125; on the parallel set p = 1.0 (the stated hypothesis, a gain on p01–p04, is not supported). Handoffs tie the single agent on v1; both its c18 failures are a phrase-list false negative ("No return has been authorized yet").
- **Supervisor failure patterns (every failed trial read):** a doubt the supervisor's brief raised ("was it opened?") coming back from the refunds specialist as a blocker (c09, c11, p06: 5 trials); refuse-then-escalate (c15, c16, c21: 5); the delivery date lost between the report and the reply (c23: 3/3, as in the Phase 6 workflow); a brief that dropped the customer's words (p08: 3).
- **Did multi-agent earn its cost? No.** Every ticket fits one context, parallel tool calls already give one agent concurrency, and our failures are information lost between agents.

### What stage 9 needs to know

- **The variant to compare against is still `graph_all`** (v1 k5 `20261029T001125Z`, adversarial k5 `20261029T003444Z`, parallel k5 `20261029T180017Z`). Multi-agent is not the deploy candidate.
- **The evaluator-optimizer can reuse the delegate hook.** A verifier is a delegate the writer must call before acting, or a node after `model`; `run_delegates` already merges a subagent's spend into the run's pool and logs it as its own agent. `act_after_reports` is the pattern for "check before act" across agents.
- **The failure patterns are evaluator targets:** refuse-then-escalate (c15, c16, c21, c22 across arms) and facts dropped from the reply (c23) are what a separate checker of "action vs policy" and "reply states the facts it used" could catch.
- **MCP:** a tool served over MCP is still a store tool to the graph; keep `execute_tool` behind it so taint, grounding, keys and the toolset guard apply unchanged. Specialists run in threads, so an MCP client used by them must be safe across threads (or one per specialist).
- **Memory:** per-agent prompts already repeat the policy; anything long-term memory adds to a prompt multiplies across agents. Keep memory in the single agent.
- **Langfuse:** the legacy trace-list API returns 410 for this organisation (removal 2026-11-16); read traces with `api.observations.get_many(from_start_time=..., trace_id=...)`. Sweeps only mirror to Langfuse with `--langfuse`.
- **Keep the Mac awake for sweeps:** `caffeinate -i` does not stop lid-close sleep; a calibration run stalled for 1h45m.

### Open questions carried forward

- Would structured briefs and reports (the customer's words verbatim, facts as fields) remove the four supervisor failure patterns? That needs a held-out split; it was not tuned on v1.
- Would a supervisor pay off with a stronger orchestrator and cheap specialists (two model tiers), or on tasks with large tool results? Neither was tested.
- Should the phrase grader handle negation ("No return has been authorized yet")? A reviewed grader change, for Phase 4.
- Handoffs on the parallel set and on the adversarial set were not run.
