# Stage 2: Eval harness and baseline

Sweeps on 2026-10-20 (UTC), all through the unchanged single round (rung 1):
- `gpt-6-luna`: 20 tasks × 5 trials;
- `gpt-5.6-luna`, `gpt-5-mini` and `claude-haiku-5-5`: 20 × 1 each.

That is 160 trials in total. Spend was **$0.093**, against a dry-run estimate of $0.20 and a Phase 2 budget of $1.50. Every number below can be regenerated from the committed files:

```
arl report --regrade results/2026*gpt-6-luna-k5.json results/2026*gpt-5.6-luna-k1.json \
  results/2026*gpt-5-mini-k1.json results/2026*claude-haiku-5-5-k1.json
```

## The concepts

| Term | Here |
|---|---|
| Task | One ticket plus its answer key: the expected database change, the disposition (resolved, refused or escalated), the reply facts, the step rules, and a reference solution |
| Trial | One attempt at one task, from a fresh store |
| Transcript | What the graders read: the model turns, the tool calls with their results, the reply, and the database diff. It is built from the JSONL trace and stored with the results |
| Grader | A pure function from (task, transcript) to checks. Code only; no model |
| Outcome grading | Did the store end up right (db), and was the customer told the right thing (facts, hygiene)? |
| Trajectory grading | Was a tool that should have been called called, was a forbidden one avoided, and was the check done before the action? |
| pass^k | Per task, C(c, k)/C(n, k): the chance that k trials all succeed. pass^1 is the success rate |
| Paired comparison | Win, loss or tie per task between two arms, with a sign test on the tasks that differ |

**What 20 tasks can resolve.**
- A two-sided sign test needs at least 6 differing tasks, all going one way, to reach p < 0.05. So a gap below about **30 points** is a *direction*.
- Trials within a task are correlated, so 5 trials sharpen the per-task rates and make pass^k meaningful, but they do not add tasks.
- Cost, tokens, latency and call counts are precise.

## How it is built

```
task YAML ──► runner: new_store() ─► run_single_round() ─► end_state event (db diff) ─► JSONL
                │  cap check before each trial                                     │
                ▼                                                                   ▼
        results/<sweep>.json  ◄── verdict + compact transcript ◄── graders ◄── Transcript.from_events
        results/spend.csv (one row per sweep)          arl report: summary, categories, variance, paired
```

- `src/arl/evals/tasks/capability/` holds 20 YAML tasks. The `Task` model rejects unknown fields. On load, the tasks are checked for consistency: refused tasks change nothing, an escalation inserts exactly one row, and every ID exists in the store.
- `dbdiff.py` snapshots each table by `id` and diffs inserts, deletes and column updates.
- `graders/outcome.py` has three checks:
  - **db**: the expected change, exactly. Free-text columns are ignored. Values match by equality, or by `contains` for text.
  - **facts**: phrases are matched after normalisation (case, quotes, dashes, `$` and thousands commas).
  - **hygiene**: a non-empty reply, an `end` stop, and no tool-call syntax.
- `graders/trajectory.py` has three checks:
  - **must_call** counts only successful calls.
  - **must_not_call** counts every attempt.
  - **order** requires the check to come in a *strictly earlier model turn* than the action.
- `runner.py`:
  - **estimate:** the request size is built exactly as it will be sent, then divided by the characters per token measured from the recorded fixtures. Once a model has been measured, its measured cost per trial replaces the prior.
  - **hard cap:** before each trial, the sweep halts if what has been spent plus that trial's worst case would cross the cap.
  - **errors:** the sweep halts after 3 consecutive error trials.
  - **output:** a results JSON and a ledger row are written in a `finally` block.
- `report.py` produces the tables, plus `--show` (one transcript, readable) and `--regrade`.
- There are 111 new tests, all without API calls.
  - Every task's reference solution is replayed against a fresh store and must pass every check.
  - A broken variant of each kind of task must fail the right check.
  - A scripted model drives the runner. One test shows the cap halting after exactly 6 of 10 trials.

## Options and what we chose

| Decision | Options | Chosen | Why |
|---|---|---|---|
| What is graded | The end state only (tau-bench), or end state plus steps | db ∧ facts ∧ hygiene ∧ trajectory, each also reported | The database cannot see a false claim of action, and a correct end state can hide an unverified write |
| Reply checking | Phrase lists now, or an LLM judge now | Phrase lists; the judge comes in Stage 4 | No model in the headline grade. The cost is brittleness (see the review) |
| "Check before act" | Earlier in the call list, or an earlier model turn | An earlier model turn | Calls in one batch are sent before any result is seen |
| Failed calls | Count them, or not | must_call: successes only; must_not_call: every attempt | A failed lookup is no lookup; an attempted forbidden write is the violation |
| API failures | Count as agent failures, or separately | Error trials, left out of the rates and counted on their own | An outage is not a wrong answer |
| Proving the tasks | Trust the author, or a replayed reference run per task | Replayed reference runs | Proves each task can be passed and that the graders accept a correct run |
| Where transcripts live | Raw JSONL only, or a compact copy in the results | Compact copy in the results (about 2 KB per trial) | `--regrade` works from a clean checkout; raw logs stay out of git |
| Cost cap | Stop after crossing it, or before | Before: spent + the trial's worst case | The cap can never be exceeded |
| Trials for the other models | 20 × 1 (the plan), or 20 × 5 | 20 × 1 | As planned. It costs us pass^k for those three models (see "limits") |

## What we measured

Rates are re-graded after the transcript review.

| Model | Success | pass^5 | Tasks always / flaky / never | db ✓ | facts ✓ | Model calls/run | Tokens in / out per run | $/run | Latency p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna (k5) | 43% | **35%** | 7 / 2 / 11 | 54% | 59% | 1.95 | 3,849 / 192 | **$0.00016** | 4.0 / 6.5 s |
| gpt-5.6-luna (k1) | 45% | – | 9 / 0 / 11 | 55% | 70% | 1.95 | 3,882 / 160 | $0.00038 | 3.4 / 4.5 s |
| gpt-5-mini (k1) | 45% | – | 9 / 0 / 11 | 55% | 80% | 1.95 | 3,812 / 1,219 | $0.0027 | 11.9 / 17.4 s |
| claude-haiku-5-5 (k1) | 50% | – | 10 / 0 / 10 | 55% | 85% | 1.90 | 7,417 / 403 | $0.00075 | 6.9 / 10.6 s |

| Category | gpt-6-luna | gpt-5.6-luna | gpt-5-mini | Haiku 5.5 |
|---|---|---|---|---|
| read (6 tasks) | 80% | 83% | 83% | 83% |
| write (6) | 0% | 0% | 0% | 0% |
| refuse (4) | 70% | 75% | 75% | 100% |
| escalate (4) | 25% | 25% | 25% | 25% |

Hygiene was 100% on every model: no `max_tokens` endings, no tool-call text, no errors.

Cost per model call:

| | Request 1 input (cached) | Request 1 $ | Request 2 input / output | Request 2 $ |
|---|---|---|---|---|
| gpt-6-luna | 1,842 (1,816 read from cache) | $0.000049 | 2,112 / 145 | $0.000119 |
| gpt-5.6-luna | 1,842 (1,720) | $0.000154 | 2,147 / 91 | $0.000236 |
| gpt-5-mini | 1,842 (1,472) | $0.000489 | 2,074 / 1,093 (893 reasoning) | $0.002331 |
| Haiku 5.5 | 3,696 (**0**; 3,692 written to the cache) | $0.000536 | 4,134 / 284 | $0.000234 |

### Findings (measured, solid at this size)

1. **Rung 1 cannot complete any write or any lookup-then-escalate task.** Writes were 0 of 60 trials across the four models, and no model called a write tool in any of the 160 trials. The only escalation passed was c19, a customer asking for a person, which can be done without a lookup. This confirms Phase 1's observation as a measured rate. It is the gap Stage 3's loop has to close.
2. **The measured ceiling of rung 1 is about 50%.** That is in line with the prediction of about 11 of 20 made before the runs.
3. **Cost and latency differ far more than success does.**
   - gpt-6-luna is the cheapest per run.
   - gpt-5.6-luna costs 2.3× as much, Haiku 4.6×, and gpt-5-mini 17×. gpt-5-mini spends about 900 reasoning tokens on each reply.
   - gpt-5-mini is also about 3× slower (p50 11.9 s).
4. **Haiku's cost is mostly cache writes.** Request 1 read 0 tokens from the cache in all 20 trials and wrote about 3,690 every time, because the top-level `cache_control` breakpoint sits after the ticket. On OpenAI, automatic caching served 98% of request 1 for gpt-6-luna.
5. **The closing instruction held.** There was no hygiene failure in 160 trials, and no false-claim phrase was caught. This answers a Phase 1 open question, with one caveat: the false-claim check is phrase-based, so this means "none found", not "none".
6. **pass^5 is 8 points below pass^1 on gpt-6-luna** (35% against 43%), because two tasks are flaky:
   - c05: once the model did not fetch the shipment, and said it could not confirm the date;
   - c15: once the model escalated in round 1, without a lookup.

### Directions (not findings)

- **Haiku's 50% against gpt-6-luna's 43%** is 3 tasks one way, sign test p = 0.25. One of the three differences is real: Haiku says "already refunded" on c16, and the OpenAI models answer "Yes, a refund was issued", which reads as a new refund. The other two are artefacts of comparing k5 against k1: a 4/5 against a 1/1 counts as a "win".
- **gpt-5.6-luna and gpt-5-mini against gpt-6-luna:** 2 tasks each, both artefacts of the same kind.

## The transcript review

We read 10 transcripts together: 2 passes and 8 failures, across all four models and every category. You confirmed my reading of all ten:
- **#3 and #5–#10:** the grader was right.
- **#1, #2 and #4: the grader was too strict.** In all three, the phrase lists were too narrow:
  - c15 did not accept "cannot authorise" or "does not allow";
  - c16 did not accept "$24" for "24.00".

  Both were fixed in the task files and the stored transcripts were re-graded. That moved gpt-5-mini from 40% to 45%; nothing else changed.
- **c16's "already" stays strict on purpose.** "Yes … allow 5–7 business days" misleads a customer whose refund went out in August.
- **No pass was too lenient.** Wrong passes are the more dangerous error, so the two passes were read first.

So 3 of 10 verdicts were wrong before the fix, and all three were facts checks. The db, hygiene and trajectory checks were right every time. This is the brittleness the Stage 4 judge is meant to address. It also argues for keeping phrase lists short and widening them only after reading transcripts. The review file is `results/review/phase2-ten-transcripts.md`.

## Model choice

The rule was fixed before the runs: highest success if it leads by more than the detectable difference, otherwise the cheapest $/run, then the lowest p95 latency. A model is excluded at more than 10% hygiene or `max_tokens` failures.
- No model leads by more than the detectable difference, and none is excluded.
- **Primary: `gpt-6-luna`**, the cheapest at $0.00016 per run.
- **Secondary: `claude-haiku-5-5`**, which is usable and the best on refusals.
- **Caveat:** rung 1 cannot write, so this choice rests on reads, refusals and cost. Stage 3 should check that the primary handles a loop before relying on it.

## Measured costs that replace the plan's estimates

The plan assumed a loop run of about 8 calls, 45,000 input tokens and 2,000 output: about $0.006 on the primary model. Measured here:
- A call carries about **1,850–2,150 input tokens** on OpenAI, about 2× that on Haiku, not about 5,600.
- On OpenAI, about **90–98% of it is read from the cache**.
- gpt-6-luna costs about **$0.00005 for request 1 and $0.00012 for a reply call.**

A 4-call loop run (look, look, act, reply) should therefore cost about **$0.0003–0.0005 on gpt-6-luna** and **$0.0012–0.0015 on Haiku** as configured. On that basis, Stage 3's planned runs come to well under the planned $3.50:
- 20 × 5 on the primary: about $0.05;
- 10 × 1 on Haiku: about $0.015;
- 10 × 1 on a $2 / $10 reference model: about $0.10.

Even with a step cap of 10 calls and a 3× margin, the total is under $0.50. The estimator's prior is deliberately cautious: no cache, 400 output tokens per call. It over-estimated these sweeps by about 2×. That is safe, but measured costs should be preferred once a model has run.

## When you would choose differently in production

- **Use more tasks.** Use more than 20 when model or prompt choices are close: about 100 tasks resolve a gap of about 10–15 points. Also keep a held-out split, so prompt tuning does not fit the test set.
- **Run k ≥ 3 on every arm you compare.** Pairing a k5 arm with k1 arms here produced fake wins. Five trials per arm on all four models would have cost about $0.35.
- **Replace phrase lists with a validated judge** for reply facts, keeping code checks for anything checkable: the database, tool calls, tool-call text. Three of our ten verdicts were phrase-list errors.
- **Grade from the stored transcript.** `--regrade` made the review fixes free. In production, store transcripts with versioned task sets and re-grade every past run whenever the answer key changes.
- **Cap spend before each trial, using the worst case,** as here, but use a per-sweep worst case calibrated from measurement when trials are expensive. The cap here was about 20× the actual spend.
- **Put an explicit cache breakpoint before the ticket** on Anthropic for many-ticket sweeps. As configured, Haiku paid 1.25× for its whole prompt on every first call.

## Limits

- The three 20 × 1 arms have no pass^k and noisy per-task rates. The paired tables against the k5 arm overstate their differences.
- One author wrote the tasks and the answer keys. Ambiguity was reduced by the replayed references and by the review, not by a second annotator.
- c15 encodes a policy reading ("refuse, not escalate") that a reasonable reader might dispute. gpt-6-luna escalated it once in 5 trials.
- The seed has three background orders delivered after SIM_TODAY (ORD-2001, -2012, -2030). The tasks avoid them; the defect is unchanged.
- `results/*.json` record `git_commit: fcf36d5-dirty`, because Phase 2 code was uncommitted when the sweeps ran.
