# Stage 1: Two providers and the full toolset

Runs on 2026-10-18 (UTC):
- `gpt-6-luna` on the OpenAI Responses API (`openai` 3.29.0);
- `claude-haiku-5-5` on the Anthropic Messages API (`anthropic` 1.13.0).

Each ticket was run once per provider per variant. The observations are illustrations, not measurements.

## The concept

An adapter translates in both directions between the shapes our code uses and one provider's wire format. The neutral layer (`src/arl/llm/`) has to hide five things:
- where tool definitions go;
- how a call comes back;
- how a result goes back;
- why the model stopped;
- how usage is counted.

One thing must not be translated: **reasoning**. OpenAI `reasoning` items and Anthropic `thinking` blocks are opaque and signed. They go back unchanged, and only to the provider that produced them. So a conversation that contains reasoning is tied to one provider.

Each response part keeps the provider's original item in `native`. An assistant turn is replayed to its own provider exactly as received. That also preserved fields we did not know about: `caller` on Anthropic `tool_use` blocks and `phase` on OpenAI messages, both new.

## What it looks like on the wire

The same tool call, request 2 of t1:

```json
// OpenAI: one flat list of items
"input": [
  {"role": "user", "content": "Hi, can you tell me the status of my order ORD-1001?"},
  {"type": "function_call", "id": "fc_089a…", "call_id": "call_ecO6…", "name": "get_order",
   "arguments": "{\"order_id\":\"ORD-1001\"}", "status": "completed"},
  {"type": "function_call_output", "call_id": "call_ecO6…", "output": "{\"order\": {…}}"},
  {"role": "user", "content": "No more tools can be used for this ticket. …"}]

// Anthropic: alternating messages of content blocks
"messages": [
  {"role": "user", "content": "Hi, can you tell me the status of my order ORD-1001?"},
  {"role": "assistant", "content": [
    {"type": "tool_use", "id": "toolu_01Rn…", "name": "get_order",
     "input": {"order_id": "ORD-1001"}, "caller": {"type": "direct"}}]},
  {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_01Rn…", "content": "{\"order\": {…}}"},
    {"type": "text", "text": "No more tools can be used for this ticket. …"}]}]
```

### Provider differences

| | OpenAI Responses | Anthropic Messages | Cosmetic or behavioural? |
|---|---|---|---|
| Tool definition | `parameters`, `type: "function"` | `input_schema` | Cosmetic |
| Call arguments | JSON string | JSON object | Cosmetic (we keep a string) |
| Call ID | `call_id` (plus the item `id`) | `id` | Cosmetic |
| Result | separate `function_call_output` item | `tool_result` block, first in a user message | Cosmetic, but Anthropic rejects the wrong order |
| Error flag on a result | none | `is_error` | Small: one more signal to the model |
| Stop reason | none; derived from `status`, `incomplete_details` and the presence of calls | `stop_reason` with 7 values | **Behavioural**: the loop's exit test must be written per provider |
| `tool_choice: none` | the model replies cleanly | without a closing instruction, broke 5 of 5 times when the model still wanted to act (see below) | **Behavioural** |
| Reasoning | encrypted `reasoning` item, returned verbatim | signed `thinking` block, returned verbatim within a tool-use turn | **Behavioural**: ties a conversation to one provider |
| Thinking visible to us | no (summary empty) | yes, with `display: "summarized"` | Audit: we can read why Haiku acted |
| Output limit | optional `max_output_tokens` | required `max_tokens`; thinking counts toward it | Behavioural: thinking can use up the reply budget |
| `input_tokens` | includes cache reads and writes | excludes both | Cost: wrong totals if not normalised |
| Tokens for the same request | 1,833 (t4) | 3,677 (t4): a different tokenizer plus a hidden 286-token tool prompt | Cost: the same price per token ≠ the same price per request |
| Caching | automatic, from 1,024 tokens, shared across tickets | opt-in `cache_control`, from 512 tokens. Top-level placement put the breakpoint after the ticket, so each ticket wrote a new entry | Cost |
| Cache write price | 1.25× input (GPT-5.6 and later) | 1.25× input (5-minute TTL) | Same, but both need a price entry |
| Strict schemas | everything required, nullable for optional fields | the same, and also no `minimum`/`maxLength`; at most 16 nullable parameters | Small: one schema serves both |
| Request ID header | `x-request-id` | `request-id` | Cosmetic |
| SDK raw body | `raw.text` is a property | `raw.text()` is a method | Cosmetic, but it crashed our first run |

## Options and what we chose

| Decision | Options | Chosen | Why |
|---|---|---|---|
| Abstraction | LiteLLM-style proxy, `init_chat_model`, or our own adapters | Two hand-written adapters, about 130 lines each | The wire format stays visible; there is no proxy dependency (LiteLLM had malicious releases this year) |
| Assistant-turn replay | Rebuild from neutral fields, or replay the native items | Native replay to the same provider; rebuild without reasoning for the other provider | Required for thinking blocks, and keeps unknown new fields |
| Unknown item types | Ignore, or fail | Fail with `ValueError` | A silently dropped item is an audit gap |
| Neutral call arguments | dict or JSON string | JSON string | `execute_tool` and its invalid-JSON path stay unchanged |
| Secondary model | `claude-haiku-4-5` (as planned) or `claude-haiku-5-5` | `claude-haiku-5-5` | 4.5 is legacy, has passed its earliest retirement date, and costs 10× more; 5.5 costs the same per token as gpt-6-luna |
| Thinking display | omitted (default) or summarized | summarized | We can read why the model acted; it costs the same |
| Fourth write tool | `create_return`, `add_order_note`, `update_customer_email` | `create_return` | It gives the model a real choice between refund and return under the 30-day rules |
| Where policy lives | In the tools, or only in the prompt | Prompt only; tools check shape, existence and impossible states | Stage 2 graders and Stage 5 guardrails need a measurable "before" |
| Constraints Anthropic rejects | Drop them, or move them into the description | Move them into the description; Pydantic still enforces them | The model reads the rule, and the tool still refuses |
| Ending the round | `tool_choice: none` alone, or with a closing instruction | With a closing instruction | See "what we observed", item 2 |

### The tools (5 read, 4 write, 1 escalate)

| Tool | Kind | What it checks |
|---|---|---|
| `find_customer`, `get_order`, `list_orders`, `get_shipment`, `get_customer` | read | that the records exist |
| `issue_refund` | write | order exists and is not cancelled; amount format `79.99`; amount > 0 |
| `cancel_order` | write | order exists; not already cancelled |
| `update_shipping_address` | write | order exists and is not cancelled; two-letter state; five-digit ZIP |
| `create_return` | write | order exists and is not cancelled; SKU is in the order (the error lists the valid ones); quantity is within what was ordered minus earlier returns |
| `escalate_to_human` | escalate | category enum; order and customer exist, or are null. It writes a row, so escalation is part of the database end state |

What a tool returns on bad input:
- an error code and a message that says what was wrong;
- for schema errors, the field's own description with an example;
- "Nothing was changed";
- for an unknown SKU or an over-quantity, the valid values.

Tool schemas use `pattern` and `enum`, which both providers' strict modes enforce at sampling time. So most of these errors are defence in depth.

## What we observed

**Run A** used `tool_choice: none` alone, t1–t8 on both providers, for $0.0079. **Run B** added a closing instruction, t3 and t5–t8 on both, for $0.0048.

| Ticket | Request-1 tools, OpenAI / Haiku | Run A, OpenAI | Run A, Haiku | Run B, OpenAI | Run B, Haiku |
|---|---|---|---|---|---|
| t1 status | `get_order` / `get_order` | correct, minimal | correct, offers tracking | — | — |
| t2 parallel | 2× `get_order` / 2× `get_order` | correct | correct | — | — |
| t3 chained | `find_customer` / same | misleading "try later" | **tool calls as text, `max_tokens`** | misleading "try later" | honest: asks for the order ID |
| t4 policy | none / none | correct | correct | — | — |
| t5 refund | `get_order` (B: + `get_shipment`) / + `get_shipment` | honest: can't confirm the date | **`KASSERT_PLACEHOLDER`** | eligible, "has not been issued" | eligible, "haven't refunded" |
| t6 cancel | `get_order` / `get_order` | misleading "can't right now" | **tool calls as text, `max_tokens`** | "hasn't been cancelled yet" | "I have not cancelled" |
| t7 address | `get_order` / `get_order` | misleading "unable right now" | **"I'm updating it now"** (false) | "couldn't update" | "haven't changed" |
| t8 >30 days | `get_order` / + `get_shipment` | can't decide (no date) | right reasoning, **claims an escalation** | can't decide (no date) | right reasoning, honest |

Costs per run were 65–306 µ$ on OpenAI and 199–1,566 µ$ on Haiku. Model-call latency was 1.2–7.7 s on both.

1. **No write tool was called on any ticket, by either model.** Both look before they act, and request 2 forbids tools. So a single round can never complete a "look up, then act" ticket. This is the structural limit the loop in Stage 3 removes, and it is why t6–t8 cannot be resolved here.
2. **Without a closing instruction, Haiku 5.5's `tool_choice: none` failed in every run where it still wanted to act.** Its thinking had decided on the next step, for example on t6: "I can go ahead and cancel it". The reply then:
   - wrote tool-call syntax as text until `max_tokens` (t3, t6, each costing about 1.5 m$ for 2,000 tokens of garbage);
   - emitted `KASSERT_PLACEHOLDER` (t5);
   - began with stray tokens (`uh`, `ots`, `molecule`);
   - claimed actions it had not taken (t7, t8).

   Tickets that needed nothing more (t1, t2, t4) were clean. I found nothing about this in Anthropic's docs. One user text block after the results ("No more tools can be used … do not say or imply that it has been done") fixed all five on Haiku. It also made OpenAI's t5–t7 replies honest instead of "try again later". OpenAI's t3 stayed misleading.
3. **Haiku looked further ahead in request 1.** On t5 and t8 it fetched the shipment in parallel, and its thinking did the 30-day arithmetic correctly (21 and 46 days). OpenAI fetched the shipment on t5 in run B but not in run A, from an identical request 1, so that is run-to-run variation.
4. **The `get_order` description change did not change t1.** Neither model fetched tracking for a "status" question. Haiku offered to.
5. **Haiku cost about 4–5× more despite equal token prices.** It counts about 2× the input tokens, writes longer replies, and, as configured, writes a new cache entry of about 3,690 tokens for every ticket. OpenAI's automatic cache was shared across tickets: request 1 of every ticket read 1,811–1,851 cached tokens.
6. **Thinking replay worked.** Request 2 carried thinking blocks unchanged in 7 of the Haiku runs, with no 400 errors. Thinking was skipped on simple calls (t1 and t2, request 1), which adaptive thinking is allowed to do.
7. **OpenAI now reports `cache_write_tokens`** and charges 1.25× input for them on GPT-5.6 and later. Phase 0 priced those tokens as normal input, so its totals were very slightly low.

Phase 1 spend in total, including the smoke runs, one crashed call and the fixture re-recording: about **$0.014**.

## When you would choose differently in production

- **Don't end a turn with `tool_choice: none` alone.** Either loop until the model stops on its own (Stage 3), or close with an explicit instruction and check the reply for tool-like text. On Anthropic, also check `stop_reason`.
- **Put a cache breakpoint on the system prompt and tools** (an explicit `cache_control` on the last tool), not top-level automatic caching, when many short conversations share a long prefix.
- **Use a gateway or `init_chat_model`** once you have more than two providers, or need fallback routing. Keep the raw-body logging either way.
- **Don't switch providers mid-conversation** once reasoning is present. Our adapters drop the other provider's reasoning, which loses context and the chain of audit.
- **Put policy invariants in the write tools** (refund ≤ paid, ownership, status rules) before real money moves. Here they are left to the prompt on purpose, until Stage 5.
- **Re-check model availability and prices on a schedule.** `claude-haiku-4-5` passed its earliest retirement date, and both providers added cache-write pricing within weeks of Phase 0.

## Limits of this stage

- One run per ticket per variant, with no grading. Stage 2 adds both.
- The write tools were exercised only in unit tests. No live run called them.
- The closing instruction was tested on 5 tickets once. It is a prompt fix, not a guarantee.
- Fixtures were recorded with the closing instruction. `tests/test_recorded.py` fails on purpose if the request shape changes. Re-record with `scripts/record_fixture.py`.
