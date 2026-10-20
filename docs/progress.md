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

Branch `feature_0918_01`. Not committed. Write-up: [stages/01-two-providers.md](stages/01-two-providers.md).

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
