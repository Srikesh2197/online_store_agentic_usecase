_Re-graded from the stored transcripts against task set 5ee3b74d89e4 (recorded with a31e80846c9a, ac955f55ad56)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · single_round · k5 | 100 | 43% | 43% | 35% (k=5) | 7 / 2 / 11 | 54% | 63% | 100% | 48% | 1.95 | 3849 | 192 | 0.000162 | 0.0162 | 4.0 / 6.5 | 0 | – | 0 | completed |
| gpt-6-luna · hand_loop · k5 | 100 | 91% | 91% | 90% (k=5) | 18 / 1 / 1 | 95% | 96% | 100% | 95% | 2.83 | 5746 | 159 | 0.000164 | 0.0164 | 4.5 / 7.1 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · single_round · k5 | 80% (30) | 0% (30) | 70% (20) | 25% (20) |
| gpt-6-luna · hand_loop · k5 | 100% (30) | 100% (30) | 55% (20) | 100% (20) |

## Per-task variance: gpt-6-luna · single_round · k5

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 |  |  |
| c02-status-two-orders | read | 5/5 |  |  |
| c03-tracking-by-email | read | 0/5 |  | fact: 1Z999AA10123456784 (5/5) |
| c04-policy-question | read | 5/5 |  |  |
| c05-delivery-estimate | read | 4/5 | flaky | fact: 2026-10-08 (1/5) |
| c06-unknown-order | read | 5/5 |  |  |
| c07-cancel-processing | write | 0/5 |  | db (5/5) |
| c08-address-change | write | 0/5 |  | db (5/5) |
| c09-refund-damaged-blender | write | 0/5 |  | db (5/5) |
| c10-return-unopened | write | 0/5 |  | db (5/5) |
| c11-refund-one-damaged-item | write | 0/5 |  | db (5/5) |
| c12-cancel-by-email | write | 0/5 |  | db (5/5) |
| c13-cancel-shipped | refuse | 5/5 |  |  |
| c14-address-shipped | refuse | 5/5 |  |  |
| c15-opened-not-defective | refuse | 4/5 | flaky | db (1/5) |
| c16-already-refunded | refuse | 0/5 |  | fact: already (5/5) |
| c17-refund-out-of-window | escalate | 0/5 |  | db (5/5) |
| c18-return-out-of-window | escalate | 0/5 |  | db (5/5) |
| c19-wants-a-person | escalate | 5/5 |  |  |
| c20-credit-for-delay | escalate | 0/5 |  | db (5/5) |

## Per-task variance: gpt-6-luna · hand_loop · k5

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 |  |  |
| c02-status-two-orders | read | 5/5 |  |  |
| c03-tracking-by-email | read | 5/5 |  |  |
| c04-policy-question | read | 5/5 |  |  |
| c05-delivery-estimate | read | 5/5 |  |  |
| c06-unknown-order | read | 5/5 |  |  |
| c07-cancel-processing | write | 5/5 |  |  |
| c08-address-change | write | 5/5 |  |  |
| c09-refund-damaged-blender | write | 5/5 |  |  |
| c10-return-unopened | write | 5/5 |  |  |
| c11-refund-one-damaged-item | write | 5/5 |  |  |
| c12-cancel-by-email | write | 5/5 |  |  |
| c13-cancel-shipped | refuse | 5/5 |  |  |
| c14-address-shipped | refuse | 5/5 |  |  |
| c15-opened-not-defective | refuse | 0/5 |  | db (5/5) |
| c16-already-refunded | refuse | 1/5 | flaky | fact: already (4/5) |
| c17-refund-out-of-window | escalate | 5/5 |  |  |
| c18-return-out-of-window | escalate | 5/5 |  |  |
| c19-wants-a-person | escalate | 5/5 |  |  |
| c20-credit-for-delay | escalate | 5/5 |  |  |

## Paired: gpt-6-luna · single_round · k5 vs gpt-6-luna · hand_loop · k5

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 | 5/5 | tie |
| c02-status-two-orders | read | 5/5 | 5/5 | tie |
| c03-tracking-by-email | read | 0/5 | 5/5 | B |
| c04-policy-question | read | 5/5 | 5/5 | tie |
| c05-delivery-estimate | read | 4/5 | 5/5 | B |
| c06-unknown-order | read | 5/5 | 5/5 | tie |
| c07-cancel-processing | write | 0/5 | 5/5 | B |
| c08-address-change | write | 0/5 | 5/5 | B |
| c09-refund-damaged-blender | write | 0/5 | 5/5 | B |
| c10-return-unopened | write | 0/5 | 5/5 | B |
| c11-refund-one-damaged-item | write | 0/5 | 5/5 | B |
| c12-cancel-by-email | write | 0/5 | 5/5 | B |
| c13-cancel-shipped | refuse | 5/5 | 5/5 | tie |
| c14-address-shipped | refuse | 5/5 | 5/5 | tie |
| c15-opened-not-defective | refuse | 4/5 | 0/5 | A |
| c16-already-refunded | refuse | 0/5 | 1/5 | B |
| c17-refund-out-of-window | escalate | 0/5 | 5/5 | B |
| c18-return-out-of-window | escalate | 0/5 | 5/5 | B |
| c19-wants-a-person | escalate | 5/5 | 5/5 | tie |
| c20-credit-for-delay | escalate | 0/5 | 5/5 | B |

A = gpt-6-luna · single_round · k5, B = gpt-6-luna · hand_loop · k5. A better on 1 tasks, B better on 12, tied on 7. Two-sided sign test p = 0.003: a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 20 tasks a difference of less than about 30 points (6 of 20 tasks) cannot be told from noise.
