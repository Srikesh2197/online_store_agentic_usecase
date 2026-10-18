# Progress

## Stage 0: First tool call — built 2026-10-12

Branch `feature_0911_01`. Not committed. Write-up: [stages/00-first-tool-call.md](stages/00-first-tool-call.md).

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
