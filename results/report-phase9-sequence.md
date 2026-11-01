_Re-graded from the stored transcripts against task set 3022abd9072e (recorded with 3022abd9072e)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k3 | 18 | 56% | 56% | 50% (k=3) | 3 / 1 / 2 | 56% | 72% | 100% | 56% | 7.39 | 17676 | 658 | 0.000662 | 0.0119 | 13.7 / 16.5 | 0 | – | 0 | completed |
| gpt-6-luna · graph_memory · k3 | 18 | 100% | 100% | 100% (k=3) | 6 / 0 / 0 | 100% | 100% | 100% | 100% | 6.28 | 15118 | 560 | 0.000543 | 0.0098 | 10.3 / 13.1 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · graph_all · k3 | 50% (6) | 50% (6) | 33% (3) | 100% (3) |
| gpt-6-luna · graph_memory · k3 | 100% (6) | 100% (6) | 100% (3) | 100% (3) |

## Sequences (two tickets, one customer)

| arm | sequences | ticket 1 | ticket 2 (headline) | both | wrong changes on ticket 2 | history chars read (ticket 2) |
|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k3 | 18 | 100% | 56% | 56% | 5 | – |
| gpt-6-luna · graph_memory · k3 | 18 | 100% | 100% | 100% | 0 | 457 |
Each ticket is graded on its own changes to the store. A wrong change: ticket 2 changed the store and its database check failed.

## Prompt cache

| arm | input tokens/run | cached |
|---|---|---|
| gpt-6-luna · graph_all · k3 | 17,676 | 92% |
| gpt-6-luna · graph_memory · k3 | 15,118 | 94% |

## Per-task variance: gpt-6-luna · graph_all · k3

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| s01-address-of-the-order-asked-about | refuse | 1/3 | flaky | db (2/3) |
| s02-second-damaged-item-same-order | write | 3/3 |  |  |
| s03-case-reference-after-escalation | read | 0/3 |  | db (3/3) |
| s04-did-the-refund-go-through | read | 3/3 |  |  |
| s05-return-of-the-sealed-mats | write | 0/3 |  | db (3/3) |
| s06-undo-a-cancellation | escalate | 3/3 |  |  |

## Per-task variance: gpt-6-luna · graph_memory · k3

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| s01-address-of-the-order-asked-about | refuse | 3/3 |  |  |
| s02-second-damaged-item-same-order | write | 3/3 |  |  |
| s03-case-reference-after-escalation | read | 3/3 |  |  |
| s04-did-the-refund-go-through | read | 3/3 |  |  |
| s05-return-of-the-sealed-mats | write | 3/3 |  |  |
| s06-undo-a-cancellation | escalate | 3/3 |  |  |

## Paired: gpt-6-luna · graph_all · k3 vs gpt-6-luna · graph_memory · k3

| task | category | A | B | better |
|---|---|---|---|---|
| s01-address-of-the-order-asked-about | refuse | 1/3 | 3/3 | B |
| s02-second-damaged-item-same-order | write | 3/3 | 3/3 | tie |
| s03-case-reference-after-escalation | read | 0/3 | 3/3 | B |
| s04-did-the-refund-go-through | read | 3/3 | 3/3 | tie |
| s05-return-of-the-sealed-mats | write | 0/3 | 3/3 | B |
| s06-undo-a-cancellation | escalate | 3/3 | 3/3 | tie |

A = gpt-6-luna · graph_all · k3, B = gpt-6-luna · graph_memory · k3. A better on 0 tasks, B better on 3, tied on 3. Two-sided sign test p = 0.250: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 6 tasks a difference of less than about 100 points (6 of 6 tasks) cannot be told from noise.
