# Failure taxonomy

**Draft 1, 2026-10-27.** Built by reading all 98 failed trials in the six Phase 2 and Phase 3
results files, re-graded with the current tasks. Read any trial with
`arl report <file> --show <task> --trial N`. The R-codes get revised after labelling, from
your critiques (draft 2).

## How it was built

1. **Open coding.** One note per failed trial: what the agent did, what the reply said, and
   which check failed.
2. **Axial coding.** Notes with the same cause were grouped into a kind. A kind is kept only
   if it has a definition that tells two cases apart, and at least one example.
3. **Who checks it.** For each kind: code, the judge, or a decision about the task itself.

A trial can have several codes. A rung-1 write task usually has A1 and an R-code: the action
was not taken, and the reply about it can be good or bad. That is why the judge grades the
reply only. Actions are code-graded.

## Action failures (code-checked)

| Code | Kind | Definition | Example | Check |
|---|---|---|---|---|
| A1 | Didn't act | The rules called for a write or an escalation and none was made | c09 gpt-6-luna r1 k1: refund qualifies, "I couldn't process it in this reply" | db, must_call |
| A2 | Didn't look | Answered or gave up without a lookup that was available and needed | c10 r1 k1: never fetched the shipment, then said the delivery date "isn't available here" | must_call where a task has one; otherwise it shows as a facts failure |
| A3 | Over-escalation | Escalated a case the rules decide | c15 r2 k2: get_order → get_shipment → escalate, after stating the refusal | db, must_not_call |
| A4 | Wrong or unverified write | Wrong amount, wrong order, a write before the check, a double write | **none observed** in 270 trials | db, order, must_not_call |

Counts of failed trials with each code, from the failed checks:

| Arm | Failed | A1 | A2 (by must_call) | A3 | Facts only |
|---|---|---|---|---|---|
| gpt-6-luna · rung 1 (k5) | 57 | 45 | 7 | 1 | 5 |
| gpt-5.6-luna · rung 1 (k1) | 11 | 9 | 1 | 0 | 1 |
| gpt-5-mini · rung 1 (k1) | 11 | 9 | 3 | 0 | 1 |
| Haiku 5.5 · rung 1 (k1) | 10 | 9 | 1 | 0 | 0 |
| gpt-6-luna · rung 2 (k5) | 9 | 0 | 0 | 5 | 4 |

Reading the transcripts finds more A2 than the checks do. c10, c11, c18 and c12 at rung 1
often skipped `get_shipment` or `list_orders`, and those tasks don't all have a read
must_call. That costs nothing: the db check already fails them. Rung 2 has **no** A1 or A2.
Its only action failure is A3.

## Reply failures (judge-checked)

Judged against the label question: *Judging the reply only, given what the tools returned,
would you send it to the customer as-is?*

| Code | Kind | Definition | Examples |
|---|---|---|---|
| R1 | Misleading framing | Literally true, but the way it's framed leads the customer to a false belief | c16 r1 and r2: "Yes. A $24 refund … was issued on August 24 … 5–7 business days" to a *repeat* request, which reads as a new refund. c11 r1: "Yes. … eligible for a $38 refund" when none was issued |
| R2 | Implied action or process not taken | Says or suggests someone will act, when no tool call set that up | c20 r1 k1: "it needs review by our support team", with no escalation. c17 r1 k2: "This needs review … as a policy exception" |
| R3 | Deflection | Pushes work back to the customer that the agent should do, or could have done with a lookup | c10 r1 k1: "Please share the delivery date" (it's in `get_shipment`). c07 r1 k1: "Please contact support to have it cancelled". c12 r1: "send me the order ID" after finding the account (`list_orders` exists) |
| R4 | Invented fact, reason or requirement | States something no tool result or policy line supports | c03 r1 k2: "I can't access your recent orders … right now. Please try again later" (no outage). c09 Haiku r1 and c11 gpt-5-mini r1: asks for a photo. c17 gpt-5-mini r1: serial number, video, troubleshooting |
| R5 | Off-policy statement or offer | Misstates a rule, or offers something the policy doesn't allow | c20 gpt-5-mini r1: "a refund … or a store credit". c16 gpt-5-mini r1: "a replacement". c15 gpt-5-mini r1 (Phase 2 #4): "request a one-time exception" |
| R6 | Dead end | Says something "still needs to be done" with no actor, no timing and no next step | c07 r1 k2: "The cancellation still needs to be completed." c18 r1 k2: "the delivery date still needs to be confirmed" |

Notes:
- **Counts come from labelling.** These are judgement calls, so they are counted from your
  labels and the judge's `failure_codes`, not from my reading.
- **R1 and R2 are the policy's own rule:** "Never say or imply that an action has been done
  unless a tool result confirms it. If you did not call the tool, say what will happen next
  instead." R6 is the second half of that rule failing.
- **Root cause of R6 at rung 1: our own harness.** The rung-1 closing instruction
  (`single_round.CLOSING_INSTRUCTION`) tells the model to "say plainly what you could not do
  in this reply and what is still needed". That produces "I couldn't … in this reply. It
  still needs to be completed" almost word for word. The instruction stopped false claims
  (Phase 1), at the price of dead ends. Rung 2 only uses it at the step cap, which never
  tripped.
- **Not a failure on its own: meta-language.** "I couldn't … in this reply" appears in almost
  every rung-1 reply. It is honest and odd. Decide while labelling whether it fails; if it
  does, it gets a code in draft 2.
- **A3 plus a truthful reply.** c15 r2: "aren't eligible … I've escalated your request." The
  reply describes what happened, so under reply-only labelling it can pass. The action
  failure is A3.

## Grader failures

| Code | Kind | Seen |
|---|---|---|
| G1 | Phrase-list false negative: a correct reply worded differently, a negation, or a number format | 5 of 20 reviewed verdicts (Phase 2: 3, Phase 3: 2), all fixed |
| G2 | Phrase-list false positive: a fact "found" by a loose phrase | c20 r1 k1: the `escalat` fact matched "support team", with no escalation. The db check failed it anyway |
| G3 | Strict fact, borderline case | c16 gpt-5-mini r1: "The ceramic mug set was refunded: REF-9001 … issued on 2026-08-24". No "already" and no "Yes"; it fails only on the strict "already" fact |

db, hygiene and trajectory were right in every reviewed case. All grader errors were phrase
lists. So the 10 new tasks keep facts to exact tokens (IDs, amounts, dates), and the judge
column covers wording.

## Spec ambiguity

| Code | Kind | Seen | Decision |
|---|---|---|---|
| S1 | The expected answer is disputable | c15: refuse, or escalate as "anything outside these rules"? | **Refuse** (decided 2026-10-27). "Opened items that are not defective cannot be returned" is a rule, so the case is inside the rules. Escalation is A3. The policy wording is a contributing cause, a candidate for a later prompt change |

## Code or judge?

| Kind | Code | Judge | Why |
|---|---|---|---|
| A1–A4 | ✓ | | The db and the tool calls are exact |
| Exact facts (IDs, amounts, dates, tracking numbers) | ✓ | | Token match is reliable for these |
| Tool-call leaks, empty reply, stop reason | ✓ | | Exact |
| R1 misleading framing | | ✓ | Depends on what the customer asked and how the reply opens |
| R2 implied action | partly | ✓ | A phrase check ("support team" without an escalation call) is brittle: an honest "I wasn't able to submit it" uses the same words (c17 r1 k1) |
| R3–R6 | | ✓ | Meaning, not tokens |

## Carry-over

- **c16 "Yes …" (R1):** measured here by the judge. A prompt change is an intervention for a
  later stage, compared against the frozen v1 baseline, not part of Phase 4.
- **c15 (A3):** stays a refusal in v1. c22 tests the same rule on a new order.
