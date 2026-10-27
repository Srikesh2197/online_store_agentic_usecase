# Stage 3: The hand-written agent loop (rung 2)

Sweeps on 2026-10-22 and 2026-10-23 (UTC), through the unchanged Phase 2 harness:
- `gpt-6-luna`, loop: 20 tasks × 5 trials;
- `claude-haiku-5-5`, loop: 10 tasks × 1, as a check on the second provider.

Spend was **$0.027** in total: $0.0255 in sweeps plus $0.0019 in 4 smoke runs. The plan allowed $3.50. To regenerate the main table:

```
arl report --regrade results/20261020T024342Z-single_round-gpt-6-luna-k5.json \
  results/20261022T094705Z-hand_loop-gpt-6-luna-k5.json
```

## The concepts

| Term | Here |
|---|---|
| The loop | Call the model. If it asks for tools, run them, append its turn and one result per call, and call it again. Stop when it answers without asking. Rung 1 is this loop unrolled once, with tools off on the second call |
| Message history | The model is stateless (`store: false`), so every request carries the ticket, each assistant turn replayed natively (reasoning included) and each batch of results. Input grows with every step |
| Stop reason | The only thing the loop branches on. `tool_calls` continues; `end`, `max_tokens`, `refusal` and `other` end the run |
| Parallel calls | One turn can ask for several tools. All of them run, in order, before the model sees any result. This is why "check before act" means an earlier *turn* |
| Tool errors as feedback | A failed tool returns `{"error", "message"}` as the result (`is_error` on Anthropic). The model reads it and can correct itself; the loop never crashes on a tool |
| Step cap | A hard limit on model calls, checked in code. It is the only safety net until Stage 5 |

## How it is built

`src/arl/foundations/hand_loop.py`, 155 lines, works with both providers through the Stage 1 adapters:

```
messages = [ticket]
for step in 1..10:
    if step == 10: append CLOSING_INSTRUCTION after the results; tools off      # the cap
    response = call_model(messages)
    if response.stop == tool_calls (and not capped): run every call, append turn + results; continue
    break
exit = completed | no_reply | step_cap | truncated | refused | stopped
```

| Stop | OpenAI source | Anthropic source | Loop action | Run status |
|---|---|---|---|---|
| tool_calls | `function_call` items | `tool_use` | run all calls, continue | – |
| end | completed, no calls | `end_turn` / `stop_sequence` | stop | completed, or no_reply if the text is empty |
| max_tokens | incomplete: max_output_tokens | `max_tokens` / `model_context_window_exceeded` | stop; **calls in the cut-off response are not run** | truncated |
| refusal | `refusal` content, or content_filter | `refusal` | stop; `stop_details` logged | refused |
| other | failed, cancelled, … | `pause_turn` | stop | stopped |

- **Cap of 10 model calls, the reply included.** That is 2.5× the longest reference solution.
  - When the cap trips, call 9's tools have already run.
  - Call 10 has tools off and Phase 1's closing instruction after the results, so the model still writes an honest reply.
  - The run's status is `step_cap`.
- **No closing instruction on the normal path.** The model is no longer cut off, which answers a Phase 1 open question.
- **Two new trace events:** `step_cap`, and `loop_exit` (exit, steps, provider stop, refusal detail).
- **Runner:** a strategy registry, with `--strategy` on `arl run` and `arl eval`.
  - The worst case now sums 10 calls whose history grows each step: $0.027 per trial on gpt-6-luna, against $0.003 for rung 1.
  - Measured costs are kept apart by strategy.
- **Report:**
  - a count of other exits;
  - **paired tables matched on k:** arms with different trial counts are compared on their first min(k) trials, which fixes Phase 2's fake wins;
  - `--tasks` to restrict to a subset of tasks.
- **Tests: 36 new, 250 in total, no API calls.**
  - The scripted fake model (`tests/scripted.py`) builds real response bodies for each provider, so the real adapters parse them.
  - It drives 29 loop tests on both providers: every stop reason, parallel calls, bad JSON, an unknown tool, a tool that raises, a truncated call never being run, the cap, reasoning replay, and a scripted run that passes the real graders.

## Options and what we chose

| Decision | Options | Chosen | Why |
|---|---|---|---|
| What ends the loop | Stop reason, or "no tool calls in the response" | Stop reason, handled per neutral value | A truncated response can contain a call; the stop reason says not to trust it |
| Truncated response | Retry with more tokens (Anthropic's documented fix), continue, or stop | Stop, status truncated | Retries are Stage 5. A cut-off call's arguments may be incomplete |
| Refusal | Retry on a fallback model, or stop | Stop and log `stop_details` | Fallback is a Stage 5 policy decision |
| Tool that raises | Crash the run, or return an error result | Error result `tool_failed`, no internals | The model can recover; the trace keeps the cause |
| When the cap trips | A model reply with tools off, a canned reply, or no reply | A model reply with tools off and the closing instruction | It held over 160 Phase 2 trials; the customer learns what was found and what was not done |
| Cap size | 6, 10 or 20 calls | 10 | 2.5× the longest reference. No trial came close |
| A second runner, or a strategy argument | — | A strategy argument | One harness, so the arms are comparable |
| Haiku cache breakpoint | Add one now, or later | Later (Stage 11) | It would change the cost basis mid-comparison. Within a loop, the automatic breakpoint already moves forward |
| Model arms (reference, Haiku rung 1) | As in PLAN.md, or cut | Cut to one Haiku loop check | The project's aim is a working agent, not the best model. gpt-6-luna was already at 50/50 on the 10 planned tasks, so a reference arm could only tie |

## What we measured

| Arm | Success | pass^5 | db ✓ | facts ✓ | trajectory ✓ | Calls/run | Tokens in / out | $/run | p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · rung 1 (k5) | 43% | 35% | 54% | 63% | 48% | 1.95 | 3,849 / 192 | $0.000162 | 4.0 / 6.5 s |
| gpt-6-luna · **rung 2** (k5) | **91%** | **90%** | 95% | 96% | 95% | 2.83 | 5,746 / 159 | $0.000164 | 4.5 / 7.1 s |
| Haiku 5.5 · rung 2 (k1, 10 tasks) | 100% | – | 100% | 100% | 100% | 2.90 | 11,980 / 548 | $0.000914 | 6.9 / 26.7 s |

| Category | read | write | refuse | escalate |
|---|---|---|---|---|
| rung 1 | 80% | 0% | 70% | 25% |
| rung 2 | 100% | **100%** | 55% | **100%** |

### Findings (measured, solid at this size)

1. **The loop roughly doubles success: 43% → 91%.** It was better on 12 tasks and worse on 1, with 7 ties; sign test p = 0.003. All 6 writes and the 3 lookup-then-escalate tasks went from 0/5 to 5/5. c03 (a three-step lookup) went from 0/5 to 5/5.
2. **It cost nothing extra per run on gpt-6-luna:** $0.000164 against $0.000162, despite 45% more calls. There are three reasons:
   - 96% of input was read from cache, against 93% at rung 1;
   - the extra calls are short (56 output tokens per call, against 98);
   - rung 1's forced reply under `tool_choice: none` wrote longer text.

   Latency rose about 0.5 s at the median.
3. **The step cap never tripped.** The longest run was 5 calls; the distribution was 1: 5, 2: 39, 3: 29, 4: 22, 5: 5. There were no truncations, refusals or empty replies.
4. **The loop lost on c15, the predicted risk:** 4/5 at rung 1, 0/5 at rung 2. The model refuses the return, then escalates as a "policy exception". Rung 1 could only escalate in request 1. The loop also escalates *after looking*, in 4 of the 5 trials. More turns means more chances to act.
5. **None of the 10 annotated failures was a wrong action.** There was no wrong write, no write before a check, and no double write. The remaining failures are judgement (c15) and wording (c16: "Yes, a refund was issued" to a repeat request).

### Directions (not findings)

- **Haiku 5.5 passed all 10 tasks** with the loop, including c15 and c16, which gpt-6-luna fails. That is one trial per task, so it is a direction. It also confirms that the Anthropic path works end to end: thinking replay, `tool_result` ordering and in-loop caching.
- **Haiku costs about 5.6× as much per run** ($0.00091). The main cause is that request 1 writes about 3,690 tokens to the cache on every ticket: its cached share was 62%, against gpt-6-luna's 96%.

### The ten-failure review

The full review is in `results/review/phase3-ten-failures.md`. You confirmed all ten readings:
- **c15 ×4 and c16 ×4: the grader was right.**
- **c11 k3 and c17 k3: phrase-list false negatives**, so 2 of 10 verdicts were wrong (Phase 2: 3 of 10). The fixes:
  - c11 now accepts "$38";
  - must_not_say no longer matches inside "**no** refund has been issued".
- **No other check was wrong.** Re-grading moved the gpt-6-luna loop from 89% to 91%. No Phase 2 arm changed.

## When you would choose differently in production

- **Retry a truncated call with a larger limit, and fall back to another model on a refusal,** each with its own budget. Both are Stage 5 here.
- **Enforce policy in the tools before a loop goes live.** The loop is what makes writes reachable. c13 held 5/5 only because the model chose not to cancel a shipped order; `cancel_order` would have let it.
- **Treat over-escalation as a cost, not a safe default.** Every escalation is work for a person. c15 shows a loop drifting toward "escalate when unsure". Make the policy explicit, or measure the escalation rate.
- **Limit by tokens, dollars and wall-clock, not only by steps.** A 10-step cap bounds calls but not their size. Haiku's p95 latency was 26.7 s.
- **Set an explicit cache breakpoint on Anthropic.** Request 1 of each ticket is now the dominant cost.

## Limits

- 20 tasks: only gaps of about 30 points or more resolve. The rung-1 against rung-2 gap is 48 points.
- The Haiku arm is 10 × 1. The PLAN.md reference-model arm was deliberately not run (see the options above).
- c15's expected disposition (refuse, not escalate) is disputed; it is carried into Stage 4.
- `results/*.json` record a `-dirty` git commit, because Phase 3 code was uncommitted when the sweeps ran.
