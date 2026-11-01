_Re-graded from the stored transcripts against task set 76254c561b0d (recorded with 76254c561b0d)._

_Restricted to 10 tasks: c01-status-shipped, c03-tracking-by-email, c07-cancel-processing, c08-address-change, c09-refund-damaged-blender, c10-return-unopened, c15-opened-not-defective, c16-already-refunded, c19-wants-a-person, c23-return-window-from-delivery._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 50 | 98% | 98% | 90% (k=5) | 9 / 1 / 0 | 100% | 98% | 100% | 100% | 2.88 | 6417 | 156 | 0.000172 | 0.0086 | 4.1 / 5.9 | 0 | – | 0 | completed |
| gpt-6-luna · graph_mcp · k3 | 30 | 93% | 93% | 80% (k=3) | 8 / 2 / 0 | 97% | 97% | 100% | 97% | 3.03 | 6776 | 161 | 0.000180 | 0.0054 | 4.4 / 6.0 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 100% (10) | 100% (25) | 90% (10) | 100% (5) |
| gpt-6-luna · graph_mcp · k3 | 100% (6) | 100% (15) | 67% (6) | 100% (3) |

## Original and failure-derived tasks

| arm | original | failure-derived |
|---|---|---|
| gpt-6-luna · graph_all · k5 | 98% (9 tasks, 45 trials) | 100% (1 tasks, 5 trials) |
| gpt-6-luna · graph_mcp · k3 | 93% (9 tasks, 27 trials) | 100% (1 tasks, 3 trials) |

## MCP: the cost of the hop

| arm | tools | connect ms (p50) | list ms (p50) | ms per tool call | p50 run latency (s) |
|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | in-process | – | – | – | 4.12 |
| gpt-6-luna · graph_mcp · k3 | stdio | 253 | 2 | 4.75 | 4.37 |
Reference = gpt-6-luna · graph_all · k5. Connect is starting the server and the handshake; a run's latency includes it.

## Prompt cache

| arm | input tokens/run | cached |
|---|---|---|
| gpt-6-luna · graph_all · k5 | 6,417 | 96% |
| gpt-6-luna · graph_mcp · k3 | 6,776 | 96% |

## Per-task variance: gpt-6-luna · graph_all · k5

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 |  |  |
| c03-tracking-by-email | read | 5/5 |  |  |
| c07-cancel-processing | write | 5/5 |  |  |
| c08-address-change | write | 5/5 |  |  |
| c09-refund-damaged-blender | write | 5/5 |  |  |
| c10-return-unopened | write | 5/5 |  |  |
| c15-opened-not-defective | refuse | 5/5 |  |  |
| c16-already-refunded | refuse | 4/5 | flaky | fact: already (1/5) |
| c19-wants-a-person | escalate | 5/5 |  |  |
| c23-return-window-from-delivery | write | 5/5 |  |  |

## Per-task variance: gpt-6-luna · graph_mcp · k3

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| c01-status-shipped | read | 3/3 |  |  |
| c03-tracking-by-email | read | 3/3 |  |  |
| c07-cancel-processing | write | 3/3 |  |  |
| c08-address-change | write | 3/3 |  |  |
| c09-refund-damaged-blender | write | 3/3 |  |  |
| c10-return-unopened | write | 3/3 |  |  |
| c15-opened-not-defective | refuse | 2/3 | flaky | db (1/3) |
| c16-already-refunded | refuse | 2/3 | flaky | fact: already (1/3) |
| c19-wants-a-person | escalate | 3/3 |  |  |
| c23-return-window-from-delivery | write | 3/3 |  |  |

## Paired: gpt-6-luna · graph_all · k5 vs gpt-6-luna · graph_mcp · k3

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 3/3 | 3/3 | tie |
| c03-tracking-by-email | read | 3/3 | 3/3 | tie |
| c07-cancel-processing | write | 3/3 | 3/3 | tie |
| c08-address-change | write | 3/3 | 3/3 | tie |
| c09-refund-damaged-blender | write | 3/3 | 3/3 | tie |
| c10-return-unopened | write | 3/3 | 3/3 | tie |
| c15-opened-not-defective | refuse | 3/3 | 2/3 | A |
| c16-already-refunded | refuse | 3/3 | 2/3 | A |
| c19-wants-a-person | escalate | 3/3 | 3/3 | tie |
| c23-return-window-from-delivery | write | 3/3 | 3/3 | tie |

A = gpt-6-luna · graph_all · k3, B = gpt-6-luna · graph_mcp · k3. A better on 2 tasks, B better on 0, tied on 8. Two-sided sign test p = 0.500: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 10 tasks a difference of less than about 60 points (6 of 10 tasks) cannot be told from noise. The arms ran k=5 and k=3, so each task is compared on its first 3 trial(s) only.
