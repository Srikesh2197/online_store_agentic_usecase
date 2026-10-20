_Re-graded from the stored transcripts against task set ac955f55ad56 (recorded with a31e80846c9a)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · single_round · k5 | 100 | 43% | 43% | 35% (k=5) | 7 / 2 / 11 | 54% | 59% | 100% | 48% | 1.95 | 3849 | 192 | 0.000162 | 0.0162 | 4.0 / 6.5 | 0 | 0 | completed |
| gpt-5.6-luna · single_round · k1 | 20 | 45% | 45% | 45% (k=1) | 9 / 0 / 11 | 55% | 70% | 100% | 50% | 1.95 | 3882 | 160 | 0.000377 | 0.0075 | 3.4 / 4.5 | 0 | 0 | completed |
| gpt-5-mini · single_round · k1 | 20 | 45% | 45% | 45% (k=1) | 9 / 0 / 11 | 55% | 80% | 100% | 50% | 1.95 | 3812 | 1219 | 0.002703 | 0.0541 | 11.9 / 17.4 | 0 | 0 | completed |
| claude-haiku-5-5 · single_round · k1 | 20 | 50% | 50% | 50% (k=1) | 10 / 0 / 10 | 55% | 85% | 100% | 50% | 1.90 | 7417 | 403 | 0.000746 | 0.0149 | 6.9 / 10.6 | 0 | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · single_round · k5 | 80% (30) | 0% (30) | 70% (20) | 25% (20) |
| gpt-5.6-luna · single_round · k1 | 83% (6) | 0% (6) | 75% (4) | 25% (4) |
| gpt-5-mini · single_round · k1 | 83% (6) | 0% (6) | 75% (4) | 25% (4) |
| claude-haiku-5-5 · single_round · k1 | 83% (6) | 0% (6) | 100% (4) | 25% (4) |

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

## Paired: gpt-6-luna · single_round · k5 vs gpt-5.6-luna · single_round · k1

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 | 1/1 | tie |
| c02-status-two-orders | read | 5/5 | 1/1 | tie |
| c03-tracking-by-email | read | 0/5 | 0/1 | tie |
| c04-policy-question | read | 5/5 | 1/1 | tie |
| c05-delivery-estimate | read | 4/5 | 1/1 | B |
| c06-unknown-order | read | 5/5 | 1/1 | tie |
| c07-cancel-processing | write | 0/5 | 0/1 | tie |
| c08-address-change | write | 0/5 | 0/1 | tie |
| c09-refund-damaged-blender | write | 0/5 | 0/1 | tie |
| c10-return-unopened | write | 0/5 | 0/1 | tie |
| c11-refund-one-damaged-item | write | 0/5 | 0/1 | tie |
| c12-cancel-by-email | write | 0/5 | 0/1 | tie |
| c13-cancel-shipped | refuse | 5/5 | 1/1 | tie |
| c14-address-shipped | refuse | 5/5 | 1/1 | tie |
| c15-opened-not-defective | refuse | 4/5 | 1/1 | B |
| c16-already-refunded | refuse | 0/5 | 0/1 | tie |
| c17-refund-out-of-window | escalate | 0/5 | 0/1 | tie |
| c18-return-out-of-window | escalate | 0/5 | 0/1 | tie |
| c19-wants-a-person | escalate | 5/5 | 1/1 | tie |
| c20-credit-for-delay | escalate | 0/5 | 0/1 | tie |

A = gpt-6-luna · single_round · k5, B = gpt-5.6-luna · single_round · k1. A better on 0 tasks, B better on 2, tied on 18. Two-sided sign test p = 0.500: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 20 tasks a difference of less than about 30 points (6 of 20 tasks) cannot be told from noise.

## Paired: gpt-6-luna · single_round · k5 vs gpt-5-mini · single_round · k1

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 | 1/1 | tie |
| c02-status-two-orders | read | 5/5 | 1/1 | tie |
| c03-tracking-by-email | read | 0/5 | 0/1 | tie |
| c04-policy-question | read | 5/5 | 1/1 | tie |
| c05-delivery-estimate | read | 4/5 | 1/1 | B |
| c06-unknown-order | read | 5/5 | 1/1 | tie |
| c07-cancel-processing | write | 0/5 | 0/1 | tie |
| c08-address-change | write | 0/5 | 0/1 | tie |
| c09-refund-damaged-blender | write | 0/5 | 0/1 | tie |
| c10-return-unopened | write | 0/5 | 0/1 | tie |
| c11-refund-one-damaged-item | write | 0/5 | 0/1 | tie |
| c12-cancel-by-email | write | 0/5 | 0/1 | tie |
| c13-cancel-shipped | refuse | 5/5 | 1/1 | tie |
| c14-address-shipped | refuse | 5/5 | 1/1 | tie |
| c15-opened-not-defective | refuse | 4/5 | 1/1 | B |
| c16-already-refunded | refuse | 0/5 | 0/1 | tie |
| c17-refund-out-of-window | escalate | 0/5 | 0/1 | tie |
| c18-return-out-of-window | escalate | 0/5 | 0/1 | tie |
| c19-wants-a-person | escalate | 5/5 | 1/1 | tie |
| c20-credit-for-delay | escalate | 0/5 | 0/1 | tie |

A = gpt-6-luna · single_round · k5, B = gpt-5-mini · single_round · k1. A better on 0 tasks, B better on 2, tied on 18. Two-sided sign test p = 0.500: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 20 tasks a difference of less than about 30 points (6 of 20 tasks) cannot be told from noise.

## Paired: gpt-6-luna · single_round · k5 vs claude-haiku-5-5 · single_round · k1

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 5/5 | 1/1 | tie |
| c02-status-two-orders | read | 5/5 | 1/1 | tie |
| c03-tracking-by-email | read | 0/5 | 0/1 | tie |
| c04-policy-question | read | 5/5 | 1/1 | tie |
| c05-delivery-estimate | read | 4/5 | 1/1 | B |
| c06-unknown-order | read | 5/5 | 1/1 | tie |
| c07-cancel-processing | write | 0/5 | 0/1 | tie |
| c08-address-change | write | 0/5 | 0/1 | tie |
| c09-refund-damaged-blender | write | 0/5 | 0/1 | tie |
| c10-return-unopened | write | 0/5 | 0/1 | tie |
| c11-refund-one-damaged-item | write | 0/5 | 0/1 | tie |
| c12-cancel-by-email | write | 0/5 | 0/1 | tie |
| c13-cancel-shipped | refuse | 5/5 | 1/1 | tie |
| c14-address-shipped | refuse | 5/5 | 1/1 | tie |
| c15-opened-not-defective | refuse | 4/5 | 1/1 | B |
| c16-already-refunded | refuse | 0/5 | 1/1 | B |
| c17-refund-out-of-window | escalate | 0/5 | 0/1 | tie |
| c18-return-out-of-window | escalate | 0/5 | 0/1 | tie |
| c19-wants-a-person | escalate | 5/5 | 1/1 | tie |
| c20-credit-for-delay | escalate | 0/5 | 0/1 | tie |

A = gpt-6-luna · single_round · k5, B = claude-haiku-5-5 · single_round · k1. A better on 0 tasks, B better on 3, tied on 17. Two-sided sign test p = 0.250: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 20 tasks a difference of less than about 30 points (6 of 20 tasks) cannot be told from noise.
