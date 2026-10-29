_Re-graded from the stored transcripts against task set 76254c561b0d (recorded with 76254c561b0d)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 150 | 98% | 98% | 93% (k=5) | 28 / 2 / 0 | 99% | 99% | 100% | 99% | 2.90 | 6532 | 176 | 0.000187 | 0.0280 | 4.6 / 8.7 | 0 | – | 0 | completed |
| gpt-6-luna · supervisor · k3 | 90 | 88% | 88% | 80% (k=3) | 24 / 5 / 1 | 91% | 93% | 100% | 91% | 5.23 | 10073 | 534 | 0.000464 | 0.0417 | 11.0 / 19.0 | 0 | – | 0 | completed |
| gpt-6-luna · handoffs · k3 | 90 | 98% | 98% | 97% (k=3) | 29 / 1 / 0 | 100% | 98% | 100% | 100% | 3.69 | 7521 | 261 | 0.000282 | 0.0254 | 6.6 / 10.8 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 100% (45) | 100% (45) | 90% (30) | 100% (30) |
| gpt-6-luna · supervisor · k3 | 100% (27) | 81% (27) | 67% (18) | 100% (18) |
| gpt-6-luna · handoffs · k3 | 100% (27) | 100% (27) | 100% (18) | 89% (18) |

## Original and failure-derived tasks

| arm | original | failure-derived |
|---|---|---|
| gpt-6-luna · graph_all · k5 | 99% (20 tasks, 100 trials) | 96% (10 tasks, 50 trials) |
| gpt-6-luna · supervisor · k3 | 90% (20 tasks, 60 trials) | 83% (10 tasks, 30 trials) |
| gpt-6-luna · handoffs · k3 | 97% (20 tasks, 60 trials) | 100% (10 tasks, 30 trials) |

## Multi-agent cost against the first arm

| arm | tasks paired | token multiplier | cost multiplier | model-call multiplier | uncached-input multiplier | p50 latency ratio | tokens/run | max tokens in a run |
|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · graph_all · k5 | 30 | 1.00× | 1.00× | 1.00× | 1.00× | 1.00× | 6,707 | 11,971 |
| gpt-6-luna · supervisor · k3 | 30 | 1.56× | 2.45× | 1.78× | 2.73× | 2.36× | 10,607 | 20,859 |
| gpt-6-luna · handoffs · k3 | 30 | 1.15× | 1.49× | 1.26× | 2.16× | 1.42× | 7,781 | 14,771 |
Reference = gpt-6-luna · graph_all · k5. A multiplier is the sum over the paired tasks of the arm's mean per run, divided by the same sum for the reference, on the first min(k) trials of each task. Tokens are input (cached included) plus output, over every model call of every agent.

## Where the calls and tokens went, by agent

| arm | agent | calls/run | tokens/run | share of tokens | cached | $/run | share of $ |
|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | supervisor | 2.51 | 5,962 | 56% | 93% | $0.000221 | 48% |
| gpt-6-luna · supervisor · k3 | orders | 1.97 | 3,456 | 33% | 92% | $0.000147 | 32% |
| gpt-6-luna · supervisor · k3 | refunds | 0.71 | 1,135 | 11% | 87% | $0.000087 | 19% |
| gpt-6-luna · supervisor · k3 | policy | 0.04 | 55 | 1% | 0% | $0.000010 | 2% |
| gpt-6-luna · handoffs · k3 | actions | 1.99 | 5,349 | 69% | 90% | $0.000184 | 65% |
| gpt-6-luna · handoffs · k3 | triage | 1.00 | 1,162 | 15% | 98% | $0.000050 | 18% |
| gpt-6-luna · handoffs · k3 | orders | 0.70 | 1,271 | 16% | 88% | $0.000048 | 17% |

## Coordination

| arm | delegations/run | handoffs/run | repeated lookups/run | specialists per turn | turns with several | their wall time vs the sum |
|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | 1.09 | 0.00 | 0.24 | 1.13 | 11 | 67.9 s of 111.1 s |
| gpt-6-luna · handoffs · k3 | 0.00 | 1.01 | 0.00 | – | 0 | – |
Repeated lookups: successful read calls in a run identical to an earlier one (same tool and arguments), by any agent.

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

## Per-task variance: gpt-6-luna · supervisor · k3

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
| c09-refund-damaged-blender | write | 2/3 | flaky | db (1/3) |
| c10-return-unopened | write | 3/3 |  |  |
| c11-refund-one-damaged-item | write | 2/3 | flaky | db (1/3) |
| c12-cancel-by-email | write | 3/3 |  |  |
| c13-cancel-shipped | refuse | 3/3 |  |  |
| c14-address-shipped | refuse | 3/3 |  |  |
| c15-opened-not-defective | refuse | 1/3 | flaky | db (2/3) |
| c16-already-refunded | refuse | 1/3 | flaky | db (2/3) |
| c17-refund-out-of-window | escalate | 3/3 |  |  |
| c18-return-out-of-window | escalate | 3/3 |  |  |
| c19-wants-a-person | escalate | 3/3 |  |  |
| c20-credit-for-delay | escalate | 3/3 |  |  |
| c21-refund-again-already-refunded | refuse | 1/3 | flaky | db (2/3) |
| c22-opened-not-defective-mats | refuse | 3/3 |  |  |
| c23-return-window-from-delivery | write | 0/3 |  | fact: 2026-09-07 (3/3) |
| c24-damaged-out-of-window | escalate | 3/3 |  |  |
| c25-tracking-by-email-late | read | 3/3 |  |  |
| c26-cancel-by-email-and-month | write | 3/3 |  |  |
| c27-never-arrived-wants-money | escalate | 3/3 |  |  |
| c28-address-change-no-address | read | 3/3 |  |  |
| c29-refund-one-of-two-units | write | 3/3 |  |  |
| c30-late-shipment-estimate | read | 3/3 |  |  |

## Per-task variance: gpt-6-luna · handoffs · k3

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
| c16-already-refunded | refuse | 3/3 |  |  |
| c17-refund-out-of-window | escalate | 3/3 |  |  |
| c18-return-out-of-window | escalate | 1/3 | flaky | must_not_say (2/3) |
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

## Paired: gpt-6-luna · graph_all · k5 vs gpt-6-luna · supervisor · k3

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
| c09-refund-damaged-blender | write | 3/3 | 2/3 | A |
| c10-return-unopened | write | 3/3 | 3/3 | tie |
| c11-refund-one-damaged-item | write | 3/3 | 2/3 | A |
| c12-cancel-by-email | write | 3/3 | 3/3 | tie |
| c13-cancel-shipped | refuse | 3/3 | 3/3 | tie |
| c14-address-shipped | refuse | 3/3 | 3/3 | tie |
| c15-opened-not-defective | refuse | 3/3 | 1/3 | A |
| c16-already-refunded | refuse | 3/3 | 1/3 | A |
| c17-refund-out-of-window | escalate | 3/3 | 3/3 | tie |
| c18-return-out-of-window | escalate | 3/3 | 3/3 | tie |
| c19-wants-a-person | escalate | 3/3 | 3/3 | tie |
| c20-credit-for-delay | escalate | 3/3 | 3/3 | tie |
| c21-refund-again-already-refunded | refuse | 3/3 | 1/3 | A |
| c22-opened-not-defective-mats | refuse | 1/3 | 3/3 | B |
| c23-return-window-from-delivery | write | 3/3 | 0/3 | A |
| c24-damaged-out-of-window | escalate | 3/3 | 3/3 | tie |
| c25-tracking-by-email-late | read | 3/3 | 3/3 | tie |
| c26-cancel-by-email-and-month | write | 3/3 | 3/3 | tie |
| c27-never-arrived-wants-money | escalate | 3/3 | 3/3 | tie |
| c28-address-change-no-address | read | 3/3 | 3/3 | tie |
| c29-refund-one-of-two-units | write | 3/3 | 3/3 | tie |
| c30-late-shipment-estimate | read | 3/3 | 3/3 | tie |

A = gpt-6-luna · graph_all · k3, B = gpt-6-luna · supervisor · k3. A better on 6 tasks, B better on 1, tied on 23. Two-sided sign test p = 0.125: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 30 tasks a difference of less than about 20 points (6 of 30 tasks) cannot be told from noise. The arms ran k=5 and k=3, so each task is compared on its first 3 trial(s) only.

## Paired: gpt-6-luna · graph_all · k5 vs gpt-6-luna · handoffs · k3

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
| c16-already-refunded | refuse | 3/3 | 3/3 | tie |
| c17-refund-out-of-window | escalate | 3/3 | 3/3 | tie |
| c18-return-out-of-window | escalate | 3/3 | 1/3 | A |
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

A = gpt-6-luna · graph_all · k3, B = gpt-6-luna · handoffs · k3. A better on 1 tasks, B better on 1, tied on 28. Two-sided sign test p = 1.000: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 30 tasks a difference of less than about 20 points (6 of 30 tasks) cannot be told from noise. The arms ran k=5 and k=3, so each task is compared on its first 3 trial(s) only.

