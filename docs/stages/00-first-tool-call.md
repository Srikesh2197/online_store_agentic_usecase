# Stage 0: First tool call (ladder rung 1)

Runs on 2026-10-12 (UTC), model `gpt-6-luna`, OpenAI Responses API, `openai` 3.29.0.
The observations below come from one run per ticket. They are illustrations, not measurements.

## The concept

A model cannot run anything. A "tool call" is the model returning structured data that names a function and its arguments. Our code runs the function and sends the result back in a second request.

A single round is: request 1 (the model answers or asks for tools), our code runs the tools, request 2 (the model writes the reply). There is no loop, so the model cannot use one tool's result to decide the next call.

## What it looks like on the wire

**We send** each tool as a JSON Schema plus a description:

```json
{"type": "function", "name": "get_order",
 "description": "Get one order by its order ID: ... It does not return tracking details; use get_shipment for those.",
 "parameters": {"type": "object",
                "properties": {"order_id": {"type": "string", "description": "The order ID, e.g. ORD-1001"}},
                "required": ["order_id"], "additionalProperties": false},
 "strict": true}
```

**The model returns** an item in `output`:

```json
{"id": "fc_0438...", "type": "function_call", "status": "completed",
 "name": "get_order", "arguments": "{\"order_id\":\"ORD-1001\"}",
 "call_id": "call_MQyBNo6pVmlEy48BfFzgdQ0T"}
```

**We send back** the original input, the model's items unchanged, and one result per call:

```json
{"type": "function_call_output", "call_id": "call_MQyBNo6pVmlEy48BfFzgdQ0T",
 "output": "{\"order\": {\"id\": \"ORD-1001\", \"status\": \"shipped\", ...}}"}
```

| Field | Who writes it | What it is for |
|---|---|---|
| `name`, `description`, `parameters` | Us | Everything the model knows about the tool |
| `strict` | Us | Guarantees the arguments match the schema |
| `name`, `arguments` in the call | The model | Its decision. `arguments` is a JSON string we must parse and validate |
| `call_id` | The model | Ties our result to the call it answers |
| `id` (`fc_...`) | OpenAI | The item's own ID. We do not use it |
| `output` in the result | Us | A string. The model sees only this, never our code |
| `tool_choice` | Us | `auto` lets the model decide; `none` forbids calls |
| `usage` | OpenAI | Tokens in, out, cached and reasoning, per request |

## Options and what we chose

| Decision | Options | Chosen | Why |
|---|---|---|---|
| Conversation state | `previous_response_id` (OpenAI stores it) or resend everything with `store: false` | Resend | Request 2 shows everything the model sees; the log is a complete audit trail; it matches Anthropic's API in stage 1 |
| Schema authoring | By hand, or generated from Pydantic | One by hand, three generated, with a test that they agree | See the format once, then keep one source of truth |
| Strict mode | On or off | On | No malformed arguments. Cost: every field is required, so optional fields become nullable |
| Ending the round | Allow more calls, or `tool_choice: "none"` on request 2 | `none`, with `tools` still sent | Every run ends in a reply |
| No tool requested | Make request 2 anyway, or stop | Stop | The reply is already in response 1 |
| Tool failures | Raise, or return an error result | Return `{"error", "message"}` | The model can only react to what it reads |
| What "raw" means | Print SDK objects, or the JSON bodies | JSON bodies | SDK objects are not the wire format |
| Trace storage | Langfuse only, or a local log plus Langfuse | JSONL per run, mirrored to Langfuse | The local file is the audit trail and needs no service |

## What we observed

| Ticket | Tool calls in response 1 | Model calls | Tokens in / out (reasoning) | Cost | Latency | Reply |
|---|---|---|---|---|---|---|
| t1 one tool | `get_order` | 2 | 1572 / 35 (0) | $0.000175 | 5.4 s | Correct, minimal |
| t2 parallel | `get_order` twice | 2 | 1730 / 80 (0) | $0.000213 | 3.5 s | Correct |
| t3 chained | `find_customer` | 2 | 1505 / 201 (146) | $0.000251 | 5.3 s | Failed, and misleading |
| t4 no tool | none | 1 | 700 / 25 (0) | $0.000082 | 1.6 s | Correct, from the policy |
| t5 refund | `get_order` | 2 | 1544 / 313 (221) | $0.000311 | 5.6 s | Correct refusal |

Total spend: $0.00103 for five tickets.

1. **Parallel calls are two items in one response (t2).** Each has its own `call_id`, and request 2 carries two `function_call_output` items matching them.
2. **A single round cannot chain (t3).** The ticket needed `find_customer`, then `list_orders`, then `get_shipment`. Request 1 could only ask for the first. The model ended with the customer ID and no way to use it.
3. **The failure was not honest (t3).** The reply was "I can't access your recent order or tracking details right now. Please try again later". Nothing was unavailable, and trying again would not help. The policy says to state what is missing. A reply can fail while the run reports `completed`, which is why stage 2 grades outcomes.
4. **The description steered the model (t1).** Asked for "status", it called `get_order` only and replied "Your order ORD-1001 is shipped." It did not fetch the carrier or delivery date. The `get_order` description says tracking lives in `get_shipment`, and the model followed it literally.
5. **The refusal held (t5).** With no refund tool, the model looked up the order, said it could not issue the refund, and did not claim it had. It did not check the delivery date against the 30-day rule, because that date is in the shipment, which it did not fetch.
6. **The tool definitions dominate cost.** A request with a one-line ticket is about 700 input tokens: the policy and four tool definitions. Request 2 resends all of it, so input tokens roughly double per round.
7. **Nothing was cached.** `cached_tokens` was 0 on every call, although request 2 repeats request 1's prefix. The prompt is probably below the provider's caching minimum. Not verified.
8. **Reasoning is occasional and costs output tokens.** Reasoning tokens were 0 on every tool-selection call and appeared only on the final replies for t3 (146) and t5 (221), the two tickets where the model had to explain a limit. On t5 they were 71% of output tokens.
9. **Latency is the model.** Tool execution took under 1 ms. Each model call took 1.3 to 3.7 s.

## When you would choose differently in production

- **Use a loop.** A single round is right only when one batch of lookups is always enough, such as a fixed "fetch then summarise" step.
- **Server-side state** (`previous_response_id`) saves resending the conversation and can improve caching, at the price of the provider holding the transcript and a less complete local record.
- **Non-strict schemas** when a tool genuinely needs optional or free-form arguments that strict mode cannot express.
- **Do not print or store full bodies** where tickets contain personal data. Log references or redact, and set retention.
- **Do not hand-write prices.** Ours are in `config/models.yaml` and will go stale; production systems reconcile against the provider's billing.
- **Sample traces** rather than exporting every run once volume exceeds the tracing plan.

## Limits of this stage

- One run per ticket. The model is not deterministic, so any of these could differ on a rerun.
- Reasoning items appeared only in final responses, so sending them back in a later request has not been exercised. Stage 3 will hit this.
- No write tools, no second provider, no grading. Those are stages 1 and 2.
