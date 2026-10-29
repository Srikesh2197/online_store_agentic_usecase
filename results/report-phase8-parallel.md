_Re-graded from the stored transcripts against task set 2cc7a9b329ed (recorded with 2cc7a9b329ed)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 40 | 92% | 92% | 75% (k=5) | 6 / 2 / 0 | 95% | 98% | 100% | 100% | 2.83 | 7797 | 526 | 0.000479 | 0.0192 | 6.9 / 15.6 | 0 | – | 0 | completed |
| gpt-6-luna · supervisor · k5 | 40 | 85% | 85% | 75% (k=5) | 6 / 2 / 0 | 85% | 90% | 100% | 92% | 6.38 | 13583 | 1507 | 0.001179 | 0.0472 | 15.4 / 25.1 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 96% (25) | 87% (15) | – | – |
| gpt-6-luna · supervisor · k5 | 100% (25) | 60% (15) | – | – |

## Multi-agent cost against the first arm

| arm | tasks paired | token multiplier | cost multiplier | model-call multiplier | uncached-input multiplier | p50 latency ratio | tokens/run | max tokens in a run |
|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 8 | 1.00× | 1.00× | 1.00× | 1.00× | 1.00× | 8,324 | 21,012 |
| gpt-6-luna · supervisor · k5 | 8 | 1.81× | 2.46× | 2.26× | 2.11× | 2.24× | 15,090 | 27,315 |
Reference = gpt-6-luna · graph_all · k5. A multiplier is the sum over the paired tasks of the arm's mean per run, divided by the same sum for the reference, on the first min(k) trials of each task. Tokens are input (cached included) plus output, over every model call of every agent.

## Where the calls and tokens went, by agent

| arm | agent | calls/run | tokens/run | share of tokens | cached | $/run | share of $ |
|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k5 | orders | 2.85 | 6,318 | 42% | 78% | $0.000554 | 47% |
| gpt-6-luna · supervisor · k5 | supervisor | 2.42 | 6,908 | 46% | 84% | $0.000419 | 36% |
| gpt-6-luna · supervisor · k5 | refunds | 1.02 | 1,769 | 12% | 84% | $0.000189 | 16% |
| gpt-6-luna · supervisor · k5 | policy | 0.07 | 96 | 1% | 0% | $0.000018 | 2% |

## Coordination

| arm | delegations/run | handoffs/run | repeated lookups/run | specialists per turn | turns with several | their wall time vs the sum |
|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k5 | 1.73 | 0.00 | 1.27 | 1.64 | 18 | 149.1 s of 287.2 s |
Repeated lookups: successful read calls in a run identical to an earlier one (same tool and arguments), by any agent.

## Per-task variance: gpt-6-luna · graph_all · k5

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| p01-late-orders-value | read | 5/5 |  |  |
| p02-return-window-value | read | 4/5 | flaky | fact: 536.99 (1/5) |
| p03-cancellable-value | read | 5/5 |  |  |
| p04-tracking-six | read | 5/5 |  |  |
| p05-status-by-email | read | 5/5 |  |  |
| p06-damage-two-orders | write | 3/5 | flaky | db (2/5) |
| p07-refund-return-status | write | 5/5 |  |  |
| p08-returns-two-orders | write | 5/5 |  |  |

## Per-task variance: gpt-6-luna · supervisor · k5

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| p01-late-orders-value | read | 5/5 |  |  |
| p02-return-window-value | read | 5/5 |  |  |
| p03-cancellable-value | read | 5/5 |  |  |
| p04-tracking-six | read | 5/5 |  |  |
| p05-status-by-email | read | 5/5 |  |  |
| p06-damage-two-orders | write | 2/5 | flaky | db (3/5) |
| p07-refund-return-status | write | 5/5 |  |  |
| p08-returns-two-orders | write | 2/5 | flaky | db (3/5) |

## Paired: gpt-6-luna · graph_all · k5 vs gpt-6-luna · supervisor · k5

| task | category | A | B | better |
|---|---|---|---|---|
| p01-late-orders-value | read | 5/5 | 5/5 | tie |
| p02-return-window-value | read | 4/5 | 5/5 | B |
| p03-cancellable-value | read | 5/5 | 5/5 | tie |
| p04-tracking-six | read | 5/5 | 5/5 | tie |
| p05-status-by-email | read | 5/5 | 5/5 | tie |
| p06-damage-two-orders | write | 3/5 | 2/5 | A |
| p07-refund-return-status | write | 5/5 | 5/5 | tie |
| p08-returns-two-orders | write | 5/5 | 2/5 | A |

A = gpt-6-luna · graph_all · k5, B = gpt-6-luna · supervisor · k5. A better on 2 tasks, B better on 1, tied on 5. Two-sided sign test p = 1.000: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 8 tasks a difference of less than about 75 points (6 of 8 tasks) cannot be told from noise.

