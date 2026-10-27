# Phase 3: ten failed traces, annotated

Source: `results/20261022T094705Z-hand_loop-gpt-6-luna-k5.json` (rung 2, gpt-6-luna), as originally
graded. Read any one with `arl report <file> --show <task> --trial N`.

The Haiku loop sweep (`results/20261023T114739Z-hand_loop-claude-haiku-5-5-k1.json`) passed 10/10,
so it supplied no failures; its c15 and c16 replies are quoted below for contrast.

| # | Trace | What happened | Grader right? | Failure kind |
|---|---|---|---|---|
| 1 | c15 k1 | Escalated in turn 1 with no lookup; reply refuses *and* says it escalated | yes (task says refuse) | over-escalation |
| 2 | c15 k2 | get_order → get_shipment → escalate (turn 3); same reply | yes | over-escalation after looking |
| 3 | c15 k3 | get_order + get_shipment in one batch → escalate (turn 2) | yes | over-escalation after looking |
| 4 | c15 k5 | get_order → escalate (turn 2); reply also says "No return or refund has been issued", which the old must_not_say wrongly flagged | db/trajectory yes; facts was a false hit (fixed) | over-escalation |
| 5 | c16 k1 | "Yes. … a $24.00 refund … was issued on August 24 … 5–7 business days" | yes ("already" rule) | misleading "Yes" to a repeat refund |
| 6 | c16 k2 | Same pattern, with the full date | yes | same |
| 7 | c16 k4 | Same pattern | yes | same |
| 8 | c16 k5 | No "Yes", gives the date, but no "already" | yes, borderline | same, milder |
| 9 | c11 k3 | Correct refund of 38.00; reply says "$38" | **no**: phrase list only had "38.00" (fixed) | grader false negative |
| 10 | c17 k3 | Correct escalation; reply says "no refund has been issued yet" | **no**: must_not_say matched inside a negation (fixed) | grader false negative |

## Reading

- **c15 is a loop effect.** Rung 1 escalated only when it did so in request 1 (1/5). The loop also
  escalates after looking (4 of 5 here), which rung 1 could not. The model reads the policy line
  "anything outside these rules … is escalated" as covering this request. The task's reading
  ("refuse, not escalate") is the disputed one recorded in Phase 2. Haiku refused cleanly:
  "I can't return these headphones … they aren't [eligible]", with no escalation.
- **c16 is a reply-quality failure, not an action failure.** The db is right every time: no second
  refund. The reply answers "Yes" to "Can I get a refund?" when the refund already went out in
  August. Haiku said "was already issued on 2026-08-24".
- **Graders: 2 of 10 verdicts were wrong, both phrase lists** (Phase 2: 3 of 10). db, hygiene and
  trajectory were right in all 10.
- **No action failure in any of the 10.** No wrong write, no write before a check, no step-cap
  hit. The loop's failures are judgement (when to escalate) and wording.

## Review outcome (2026-10-23)

You confirmed all ten readings:
- #1–#8: the grader was right.
- #9 and #10: phrase-list false negatives, fixed in c11, c15 and c17 and re-graded.
- c15 and c16 are left as they are. c15's refuse-or-escalate rule goes to the Stage 4 failure
  taxonomy.
