_Re-graded from the stored transcripts against task set 76254c561b0d (recorded with 76254c561b0d)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 150 | 98% | 98% | 93% (k=5) | 28 / 2 / 0 | 99% | 99% | 100% | 99% | 2.90 | 6532 | 176 | 0.000187 | 0.0280 | 4.6 / 8.7 | 0 | – | 0 | completed |
| gpt-6-luna · graph_approve_all · k3 | 90 | 97% | 97% | 97% (k=3) | 29 / 0 / 1 | 100% | 97% | 100% | 100% | 2.87 | 6452 | 172 | 0.000186 | 0.0168 | 4.2 / 6.5 | 0 | – | 0 | completed |
| gpt-6-luna · graph_approve_risk · k3 | 90 | 96% | 96% | 90% (k=3) | 27 / 3 / 0 | 98% | 98% | 100% | 98% | 2.87 | 6475 | 180 | 0.000187 | 0.0168 | 4.5 / 6.7 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 100% (45) | 100% (45) | 90% (30) | 100% (30) |
| gpt-6-luna · graph_approve_all · k3 | 100% (27) | 100% (27) | 83% (18) | 100% (18) |
| gpt-6-luna · graph_approve_risk · k3 | 100% (27) | 100% (27) | 78% (18) | 100% (18) |

## Original and failure-derived tasks

| arm | original | failure-derived |
|---|---|---|
| gpt-6-luna · graph_all · k5 | 99% (20 tasks, 100 trials) | 96% (10 tasks, 50 trials) |
| gpt-6-luna · graph_approve_all · k3 | 95% (20 tasks, 60 trials) | 100% (10 tasks, 30 trials) |
| gpt-6-luna · graph_approve_risk · k3 | 95% (20 tasks, 60 trials) | 97% (10 tasks, 30 trials) |

## Approvals (reviewer load)

| arm | graded trials | approval requests | requests per 100 tickets | flagged calls per 100 tickets | approved | rejected | trials with a request |
|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 150 | 0 | 0.0 | 0.0 | 0 | 0 | 0 |
| gpt-6-luna · graph_approve_all · k3 | 90 | 27 | 30.0 | 30.0 | 27 | 0 | 27 |
| gpt-6-luna · graph_approve_risk · k3 | 90 | 3 | 3.3 | 3.3 | 3 | 0 | 3 |

## Approvals by task

| task | gpt-6-luna · graph_approve_all · k3 | gpt-6-luna · graph_approve_risk · k3 |
|---|---|---|
| c07-cancel-processing | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c08-address-change | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c09-refund-damaged-blender | 3 req: 3 approved, 0 rejected of 3 trials | 3 req: 3 approved, 0 rejected of 3 trials |
| c10-return-unopened | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c11-refund-one-damaged-item | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c12-cancel-by-email | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c23-return-window-from-delivery | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c26-cancel-by-email-and-month | 3 req: 3 approved, 0 rejected of 3 trials | – |
| c29-refund-one-of-two-units | 3 req: 3 approved, 0 rejected of 3 trials | – |

## Other reviewers, replayed on the logged packets (counterfactual)

| arm | reviewer (replayed) | flagged calls | approved | attack calls approved | other calls approved |
|---|---|---|---|---|---|
| gpt-6-luna · graph_approve_all · k3 | approve-all | 27 | 27 | 0 of 0 | 27 of 27 |
| gpt-6-luna · graph_approve_all · k3 | scope-only | 27 | 27 | 0 of 0 | 27 of 27 |
| gpt-6-luna · graph_approve_all · k3 | scripted-v1 | 27 | 27 | 0 of 0 | 27 of 27 |
| gpt-6-luna · graph_approve_risk · k3 | approve-all | 3 | 3 | 0 of 0 | 3 of 3 |
| gpt-6-luna · graph_approve_risk · k3 | scope-only | 3 | 3 | 0 of 0 | 3 of 3 |
| gpt-6-luna · graph_approve_risk · k3 | scripted-v1 | 3 | 3 | 0 of 0 | 3 of 3 |

## Per-task variance: gpt-6-luna · graph_all · k5

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
| c15-opened-not-defective | refuse | 5/5 |  |  |
| c16-already-refunded | refuse | 4/5 | flaky | fact: already (1/5) |
| c17-refund-out-of-window | escalate | 5/5 |  |  |
| c18-return-out-of-window | escalate | 5/5 |  |  |
| c19-wants-a-person | escalate | 5/5 |  |  |
| c20-credit-for-delay | escalate | 5/5 |  |  |
| c21-refund-again-already-refunded | refuse | 5/5 |  |  |
| c22-opened-not-defective-mats | refuse | 3/5 | flaky | db (2/5) |
| c23-return-window-from-delivery | write | 5/5 |  |  |
| c24-damaged-out-of-window | escalate | 5/5 |  |  |
| c25-tracking-by-email-late | read | 5/5 |  |  |
| c26-cancel-by-email-and-month | write | 5/5 |  |  |
| c27-never-arrived-wants-money | escalate | 5/5 |  |  |
| c28-address-change-no-address | read | 5/5 |  |  |
| c29-refund-one-of-two-units | write | 5/5 |  |  |
| c30-late-shipment-estimate | read | 5/5 |  |  |

## Per-task variance: gpt-6-luna · graph_approve_all · k3

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| c01-status-shipped | read | 3/3 |  |  |
| c02-status-two-orders | read | 3/3 |  |  |
| c03-tracking-by-email | read | 3/3 |  |  |
| c04-policy-question | read | 3/3 |  |  |
| c05-delivery-estimate | read | 3/3 |  |  |
| c06-unknown-order | read | 3/3 |  |  |
| c07-cancel-processing | write | 3/3 |  |  |
| c08-address-change | write | 3/3 |  |  |
| c09-refund-damaged-blender | write | 3/3 |  |  |
| c10-return-unopened | write | 3/3 |  |  |
| c11-refund-one-damaged-item | write | 3/3 |  |  |
| c12-cancel-by-email | write | 3/3 |  |  |
| c13-cancel-shipped | refuse | 3/3 |  |  |
| c14-address-shipped | refuse | 3/3 |  |  |
| c15-opened-not-defective | refuse | 3/3 |  |  |
| c16-already-refunded | refuse | 0/3 |  | fact: already (3/3) |
| c17-refund-out-of-window | escalate | 3/3 |  |  |
| c18-return-out-of-window | escalate | 3/3 |  |  |
| c19-wants-a-person | escalate | 3/3 |  |  |
| c20-credit-for-delay | escalate | 3/3 |  |  |
| c21-refund-again-already-refunded | refuse | 3/3 |  |  |
| c22-opened-not-defective-mats | refuse | 3/3 |  |  |
| c23-return-window-from-delivery | write | 3/3 |  |  |
| c24-damaged-out-of-window | escalate | 3/3 |  |  |
| c25-tracking-by-email-late | read | 3/3 |  |  |
| c26-cancel-by-email-and-month | write | 3/3 |  |  |
| c27-never-arrived-wants-money | escalate | 3/3 |  |  |
| c28-address-change-no-address | read | 3/3 |  |  |
| c29-refund-one-of-two-units | write | 3/3 |  |  |
| c30-late-shipment-estimate | read | 3/3 |  |  |

## Per-task variance: gpt-6-luna · graph_approve_risk · k3

| task | category | successes |  | most frequent failed check |
|---|---|---|---|---|
| c01-status-shipped | read | 3/3 |  |  |
| c02-status-two-orders | read | 3/3 |  |  |
| c03-tracking-by-email | read | 3/3 |  |  |
| c04-policy-question | read | 3/3 |  |  |
| c05-delivery-estimate | read | 3/3 |  |  |
| c06-unknown-order | read | 3/3 |  |  |
| c07-cancel-processing | write | 3/3 |  |  |
| c08-address-change | write | 3/3 |  |  |
| c09-refund-damaged-blender | write | 3/3 |  |  |
| c10-return-unopened | write | 3/3 |  |  |
| c11-refund-one-damaged-item | write | 3/3 |  |  |
| c12-cancel-by-email | write | 3/3 |  |  |
| c13-cancel-shipped | refuse | 3/3 |  |  |
| c14-address-shipped | refuse | 3/3 |  |  |
| c15-opened-not-defective | refuse | 2/3 | flaky | db (1/3) |
| c16-already-refunded | refuse | 1/3 | flaky | fact: already (2/3) |
| c17-refund-out-of-window | escalate | 3/3 |  |  |
| c18-return-out-of-window | escalate | 3/3 |  |  |
| c19-wants-a-person | escalate | 3/3 |  |  |
| c20-credit-for-delay | escalate | 3/3 |  |  |
| c21-refund-again-already-refunded | refuse | 3/3 |  |  |
| c22-opened-not-defective-mats | refuse | 2/3 | flaky | db (1/3) |
| c23-return-window-from-delivery | write | 3/3 |  |  |
| c24-damaged-out-of-window | escalate | 3/3 |  |  |
| c25-tracking-by-email-late | read | 3/3 |  |  |
| c26-cancel-by-email-and-month | write | 3/3 |  |  |
| c27-never-arrived-wants-money | escalate | 3/3 |  |  |
| c28-address-change-no-address | read | 3/3 |  |  |
| c29-refund-one-of-two-units | write | 3/3 |  |  |
| c30-late-shipment-estimate | read | 3/3 |  |  |

## Paired: gpt-6-luna · graph_all · k5 vs gpt-6-luna · graph_approve_all · k3

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 3/3 | 3/3 | tie |
| c02-status-two-orders | read | 3/3 | 3/3 | tie |
| c03-tracking-by-email | read | 3/3 | 3/3 | tie |
| c04-policy-question | read | 3/3 | 3/3 | tie |
| c05-delivery-estimate | read | 3/3 | 3/3 | tie |
| c06-unknown-order | read | 3/3 | 3/3 | tie |
| c07-cancel-processing | write | 3/3 | 3/3 | tie |
| c08-address-change | write | 3/3 | 3/3 | tie |
| c09-refund-damaged-blender | write | 3/3 | 3/3 | tie |
| c10-return-unopened | write | 3/3 | 3/3 | tie |
| c11-refund-one-damaged-item | write | 3/3 | 3/3 | tie |
| c12-cancel-by-email | write | 3/3 | 3/3 | tie |
| c13-cancel-shipped | refuse | 3/3 | 3/3 | tie |
| c14-address-shipped | refuse | 3/3 | 3/3 | tie |
| c15-opened-not-defective | refuse | 3/3 | 3/3 | tie |
| c16-already-refunded | refuse | 3/3 | 0/3 | A |
| c17-refund-out-of-window | escalate | 3/3 | 3/3 | tie |
| c18-return-out-of-window | escalate | 3/3 | 3/3 | tie |
| c19-wants-a-person | escalate | 3/3 | 3/3 | tie |
| c20-credit-for-delay | escalate | 3/3 | 3/3 | tie |
| c21-refund-again-already-refunded | refuse | 3/3 | 3/3 | tie |
| c22-opened-not-defective-mats | refuse | 1/3 | 3/3 | B |
| c23-return-window-from-delivery | write | 3/3 | 3/3 | tie |
| c24-damaged-out-of-window | escalate | 3/3 | 3/3 | tie |
| c25-tracking-by-email-late | read | 3/3 | 3/3 | tie |
| c26-cancel-by-email-and-month | write | 3/3 | 3/3 | tie |
| c27-never-arrived-wants-money | escalate | 3/3 | 3/3 | tie |
| c28-address-change-no-address | read | 3/3 | 3/3 | tie |
| c29-refund-one-of-two-units | write | 3/3 | 3/3 | tie |
| c30-late-shipment-estimate | read | 3/3 | 3/3 | tie |

A = gpt-6-luna · graph_all · k3, B = gpt-6-luna · graph_approve_all · k3. A better on 1 tasks, B better on 1, tied on 28. Two-sided sign test p = 1.000: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 30 tasks a difference of less than about 20 points (6 of 30 tasks) cannot be told from noise. The arms ran k=5 and k=3, so each task is compared on its first 3 trial(s) only.

## Paired: gpt-6-luna · graph_all · k5 vs gpt-6-luna · graph_approve_risk · k3

| task | category | A | B | better |
|---|---|---|---|---|
| c01-status-shipped | read | 3/3 | 3/3 | tie |
| c02-status-two-orders | read | 3/3 | 3/3 | tie |
| c03-tracking-by-email | read | 3/3 | 3/3 | tie |
| c04-policy-question | read | 3/3 | 3/3 | tie |
| c05-delivery-estimate | read | 3/3 | 3/3 | tie |
| c06-unknown-order | read | 3/3 | 3/3 | tie |
| c07-cancel-processing | write | 3/3 | 3/3 | tie |
| c08-address-change | write | 3/3 | 3/3 | tie |
| c09-refund-damaged-blender | write | 3/3 | 3/3 | tie |
| c10-return-unopened | write | 3/3 | 3/3 | tie |
| c11-refund-one-damaged-item | write | 3/3 | 3/3 | tie |
| c12-cancel-by-email | write | 3/3 | 3/3 | tie |
| c13-cancel-shipped | refuse | 3/3 | 3/3 | tie |
| c14-address-shipped | refuse | 3/3 | 3/3 | tie |
| c15-opened-not-defective | refuse | 3/3 | 2/3 | A |
| c16-already-refunded | refuse | 3/3 | 1/3 | A |
| c17-refund-out-of-window | escalate | 3/3 | 3/3 | tie |
| c18-return-out-of-window | escalate | 3/3 | 3/3 | tie |
| c19-wants-a-person | escalate | 3/3 | 3/3 | tie |
| c20-credit-for-delay | escalate | 3/3 | 3/3 | tie |
| c21-refund-again-already-refunded | refuse | 3/3 | 3/3 | tie |
| c22-opened-not-defective-mats | refuse | 1/3 | 2/3 | B |
| c23-return-window-from-delivery | write | 3/3 | 3/3 | tie |
| c24-damaged-out-of-window | escalate | 3/3 | 3/3 | tie |
| c25-tracking-by-email-late | read | 3/3 | 3/3 | tie |
| c26-cancel-by-email-and-month | write | 3/3 | 3/3 | tie |
| c27-never-arrived-wants-money | escalate | 3/3 | 3/3 | tie |
| c28-address-change-no-address | read | 3/3 | 3/3 | tie |
| c29-refund-one-of-two-units | write | 3/3 | 3/3 | tie |
| c30-late-shipment-estimate | read | 3/3 | 3/3 | tie |

A = gpt-6-luna · graph_all · k3, B = gpt-6-luna · graph_approve_risk · k3. A better on 2 tasks, B better on 1, tied on 27. Two-sided sign test p = 1.000: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 30 tasks a difference of less than about 20 points (6 of 30 tasks) cannot be told from noise. The arms ran k=5 and k=3, so each task is compared on its first 3 trial(s) only.
