_Re-graded from the stored transcripts against task set 76254c561b0d (recorded with 5ee3b74d89e4, 76254c561b0d)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 · hand_loop · k1 | 10 | 100% | 100% | 100% (k=1) | 10 / 0 / 0 | 100% | 100% | 100% | 100% | 2.90 | 11980 | 548 | 0.000914 | 0.0091 | 6.9 / 26.7 | 0 | – | 0 | completed |
| claude-haiku-5-5 · graph_all · k1 | 10 | 100% | 100% | 100% (k=1) | 10 / 0 / 0 | 100% | 100% | 100% | 100% | 2.90 | 12782 | 588 | 0.000974 | 0.0097 | 6.0 / 9.7 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| claude-haiku-5-5 · hand_loop · k1 | – | 100% (4) | 100% (3) | 100% (3) |
| claude-haiku-5-5 · graph_all · k1 | – | 100% (4) | 100% (3) | 100% (3) |

## Paired: claude-haiku-5-5 · hand_loop · k1 vs claude-haiku-5-5 · graph_all · k1

| task | category | A | B | better |
|---|---|---|---|---|
| c09-refund-damaged-blender | write | 1/1 | 1/1 | tie |
| c10-return-unopened | write | 1/1 | 1/1 | tie |
| c11-refund-one-damaged-item | write | 1/1 | 1/1 | tie |
| c12-cancel-by-email | write | 1/1 | 1/1 | tie |
| c13-cancel-shipped | refuse | 1/1 | 1/1 | tie |
| c15-opened-not-defective | refuse | 1/1 | 1/1 | tie |
| c16-already-refunded | refuse | 1/1 | 1/1 | tie |
| c17-refund-out-of-window | escalate | 1/1 | 1/1 | tie |
| c18-return-out-of-window | escalate | 1/1 | 1/1 | tie |
| c20-credit-for-delay | escalate | 1/1 | 1/1 | tie |

A = claude-haiku-5-5 · hand_loop · k1, B = claude-haiku-5-5 · graph_all · k1. A better on 0 tasks, B better on 0, tied on 10. Two-sided sign test p = 1.000: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 10 tasks a difference of less than about 60 points (6 of 10 tasks) cannot be told from noise.

