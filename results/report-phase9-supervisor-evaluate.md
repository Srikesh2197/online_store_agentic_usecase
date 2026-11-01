_Re-graded from the stored transcripts against task set 76254c561b0d (recorded with 76254c561b0d)._

## Summary

| arm | trials | success | pass^1 | pass^k | tasks always / flaky / never | db ✓ | facts ✓ | hygiene ✓ | trajectory ✓ | model calls/run | tokens in/run | tokens out/run | $/run | $ total | latency p50 / p95 s | max_tokens endings | other exits | errors | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | 90 | 88% | 88% | 80% (k=3) | 24 / 5 / 1 | 91% | 93% | 100% | 91% | 5.23 | 10073 | 534 | 0.000464 | 0.0417 | 11.0 / 19.0 | 0 | – | 0 | completed |
| gpt-6-luna · supervisor_evaluate · k3 | 90 | 97% | 97% | 93% (k=3) | 28 / 2 / 0 | 97% | 99% | 100% | 97% | 6.73 | 12227 | 748 | 0.000655 | 0.0589 | 13.9 / 27.0 | 0 | – | 0 | completed |

## Success by category

| arm | read (trials) | write (trials) | refuse (trials) | escalate (trials) |
|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | 100% (27) | 81% (27) | 67% (18) | 100% (18) |
| gpt-6-luna · supervisor_evaluate · k3 | 100% (27) | 96% (27) | 89% (18) | 100% (18) |

## Original and failure-derived tasks

| arm | original | failure-derived |
|---|---|---|
| gpt-6-luna · supervisor · k3 | 90% (20 tasks, 60 trials) | 83% (10 tasks, 30 trials) |
| gpt-6-luna · supervisor_evaluate · k3 | 95% (20 tasks, 60 trials) | 100% (10 tasks, 30 trials) |

## Multi-agent cost against the first arm

| arm | tasks paired | token multiplier | cost multiplier | model-call multiplier | uncached-input multiplier | p50 latency ratio | tokens/run | max tokens in a run |
|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | 30 | 1.00× | 1.00× | 1.00× | 1.00× | 1.00× | 10,607 | 20,859 |
| gpt-6-luna · supervisor_evaluate · k3 | 30 | 1.22× | 1.41× | 1.29× | 1.65× | 1.27× | 12,974 | 22,349 |
Reference = gpt-6-luna · supervisor · k3. A multiplier is the sum over the paired tasks of the arm's mean per run, divided by the same sum for the reference, on the first min(k) trials of each task. Tokens are input (cached included) plus output, over every model call of every agent.

## Where the calls and tokens went, by agent

| arm | agent | calls/run | tokens/run | share of tokens | cached | $/run | share of $ |
|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | supervisor | 2.51 | 5,962 | 56% | 93% | $0.000221 | 48% |
| gpt-6-luna · supervisor · k3 | orders | 1.97 | 3,456 | 33% | 92% | $0.000147 | 32% |
| gpt-6-luna · supervisor · k3 | refunds | 0.71 | 1,135 | 11% | 87% | $0.000087 | 19% |
| gpt-6-luna · supervisor · k3 | policy | 0.04 | 55 | 1% | 0% | $0.000010 | 2% |
| gpt-6-luna · supervisor_evaluate · k3 | supervisor | 2.62 | 6,219 | 48% | 93% | $0.000227 | 35% |
| gpt-6-luna · supervisor_evaluate · k3 | evaluator | 1.50 | 2,345 | 18% | 75% | $0.000204 | 31% |
| gpt-6-luna · supervisor_evaluate · k3 | orders | 1.90 | 3,287 | 25% | 92% | $0.000133 | 20% |
| gpt-6-luna · supervisor_evaluate · k3 | refunds | 0.68 | 1,082 | 8% | 85% | $0.000084 | 13% |
| gpt-6-luna · supervisor_evaluate · k3 | policy | 0.03 | 41 | 0% | 0% | $0.000007 | 1% |

## Coordination

| arm | delegations/run | handoffs/run | repeated lookups/run | specialists per turn | turns with several | their wall time vs the sum |
|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor · k3 | 1.09 | 0.00 | 0.24 | 1.13 | 11 | 67.9 s of 111.1 s |
| gpt-6-luna · supervisor_evaluate · k3 | 1.07 | 0.00 | 0.27 | 1.10 | 9 | 92.6 s of 130.2 s |
Repeated lookups: successful read calls in a run identical to an earlier one (same tool and arguments), by any agent.

## Evaluator

| arm | checks/run | action checks/run | reply checks/run | runs sent back | sent back: actions / replies | sent-back runs that passed | unreadable verdicts | evaluator $/run | evaluator share of $ |
|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor_evaluate · k3 | 1.50 | 0.59 | 0.91 | 13 (14%) | 8 / 5 | 12/13 | 0 | $0.000204 | 31% |
At most one revision per run. A sent-back batch never ran; its calls are drafts, logged as evaluator_verdict events, not tool calls.

## Evaluator: cost per point of success gained

| arm | tasks | k | reference success | arm success | points gained | reference $/run | arm $/run | cost × | extra $/run per point gained |
|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna · supervisor_evaluate · k3 | 30 | 3 | 88% | 97% | +8.9 | $0.000464 | $0.000655 | 1.41× | $0.000021 |
Reference = gpt-6-luna · supervisor · k3. Whether the gain is a finding is in the paired table below.

## Sent-back proposals counted as attempts (strict reading)

| arm | success | passes that sent back a forbidden call | success, strict reading |
|---|---|---|---|
| gpt-6-luna · supervisor_evaluate · k3 | 97% | 8 | 88% |

## Prompt cache

| arm | input tokens/run | cached |
|---|---|---|
| gpt-6-luna · supervisor · k3 | 10,073 | 92% |
| gpt-6-luna · supervisor_evaluate · k3 | 12,227 | 89% |

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

## Per-task variance: gpt-6-luna · supervisor_evaluate · k3

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
| c11-refund-one-damaged-item | write | 2/3 | flaky | db (1/3) |
| c12-cancel-by-email | write | 3/3 |  |  |
| c13-cancel-shipped | refuse | 3/3 |  |  |
| c14-address-shipped | refuse | 3/3 |  |  |
| c15-opened-not-defective | refuse | 3/3 |  |  |
| c16-already-refunded | refuse | 1/3 | flaky | db (2/3) |
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

## Paired: gpt-6-luna · supervisor · k3 vs gpt-6-luna · supervisor_evaluate · k3

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
| c09-refund-damaged-blender | write | 2/3 | 3/3 | B |
| c10-return-unopened | write | 3/3 | 3/3 | tie |
| c11-refund-one-damaged-item | write | 2/3 | 2/3 | tie |
| c12-cancel-by-email | write | 3/3 | 3/3 | tie |
| c13-cancel-shipped | refuse | 3/3 | 3/3 | tie |
| c14-address-shipped | refuse | 3/3 | 3/3 | tie |
| c15-opened-not-defective | refuse | 1/3 | 3/3 | B |
| c16-already-refunded | refuse | 1/3 | 1/3 | tie |
| c17-refund-out-of-window | escalate | 3/3 | 3/3 | tie |
| c18-return-out-of-window | escalate | 3/3 | 3/3 | tie |
| c19-wants-a-person | escalate | 3/3 | 3/3 | tie |
| c20-credit-for-delay | escalate | 3/3 | 3/3 | tie |
| c21-refund-again-already-refunded | refuse | 1/3 | 3/3 | B |
| c22-opened-not-defective-mats | refuse | 3/3 | 3/3 | tie |
| c23-return-window-from-delivery | write | 0/3 | 3/3 | B |
| c24-damaged-out-of-window | escalate | 3/3 | 3/3 | tie |
| c25-tracking-by-email-late | read | 3/3 | 3/3 | tie |
| c26-cancel-by-email-and-month | write | 3/3 | 3/3 | tie |
| c27-never-arrived-wants-money | escalate | 3/3 | 3/3 | tie |
| c28-address-change-no-address | read | 3/3 | 3/3 | tie |
| c29-refund-one-of-two-units | write | 3/3 | 3/3 | tie |
| c30-late-shipment-estimate | read | 3/3 | 3/3 | tie |

A = gpt-6-luna · supervisor · k3, B = gpt-6-luna · supervisor_evaluate · k3. A better on 0 tasks, B better on 4, tied on 26. Two-sided sign test p = 0.125: a direction, not a finding. A sign test reaches p < 0.05 only when at least 6 differing tasks all go one way, so on 30 tasks a difference of less than about 20 points (6 of 30 tasks) cannot be told from noise.
