# Brief: Northline support agent, week-of traces

You are embedded with the modeling team that owns `nl-support-mix-3`, the model behind Northline Apparel's chat support agent. CX and finance both have complaints. Preference evals and the internal LLM judge look fine.

Do not retrain anything. Turn this week's traces plus one customer note into loss patterns the team can measure and assign.

Timebox: 30-45 minutes. Written deliverable, 1-2 pages. No code required. Cluster the 38 traces; do not write a paragraph per id.

## Materials

| Path | What it is |
| --- | --- |
| `schema/tools.md` | Tools the agent can call, including required fields |
| `customer_note.md` | Slack dump from the CX lead. Unedited. |
| `traces.jsonl` | 38 sessions. One JSON object per line. Multi-turn. |

`tags_gold` is empty in the packet. Do not assume every trace is a failure.

## Trace fields

`id`, `ts`, `user` (opening message), `turns`, `outcome` (`resolved` | `failed` | `escalated`), `tags_gold`.

A turn is `{role, content, tool_call, tool_result}`. `role` is `user`, `assistant`, or `tool`. When the assistant calls a tool, `tool_call` is `{name, args}`. The next turn is usually `role: tool` with `tool_result`.

## Policy the agent was supposed to follow

- Look up an order by `order_id` before you act on it.
- Refunds only within 30 days of delivery, and not on final-sale / outlet SKUs.
- `create_refund` requires `order_id`, `amount_cents` (integer), and `reason_code`.
- Never tell the customer a refund was issued unless `create_refund` returned success.
- If ineligible, explain the policy. Do not "just this once."
- Escalate when you cannot finish with the tools you have.

## Deliverable

### 1. Cluster failure modes

Group traces that fail, or that succeed for the wrong reason. For each cluster: a short name, what you saw in the turns, and example ids. Include the clean successes so it is obvious you did not pattern-match "everything is bad."

### 2. Map the customer note

The CX lead is not a modeler. Translate their complaint into the clusters from (1). Quote or paraphrase the line you are mapping. If they describe a mode you cannot find in the traces, say so.

### 3. Propose 2-4 loss patterns

For each pattern:

| Field | Meaning |
| --- | --- |
| **Name** | Something a dashboard can say. Not a vibe. |
| **Definition** | Observable in a trace. Boolean or countable. |
| **Metric** | Numerator / denominator, and over what slice. |
| **Stage that owns the fix** | Exactly one primary: **SFT coverage/mix**, **preference data**, **judge**, **harness**, or **RL**. A secondary is allowed if you justify it. |
| **Why that stage** | One or two sentences. |

"Agent is unhelpful" is not a loss pattern.

### 4. What not to do first

Name the move you would block this week (example: spinning an RL run, relabeling prefs, rewriting the judge, or treating a 5x identical retry as "needs more RL") and why the traces do not support it yet.

## How we read the writeup

- You opened the JSONL (tool names, args, results), not just the last assistant message.
- You connected a customer sentence to a named mode, not to "quality."
- You separated "sounds good" from "did the tool succeed."
- You assigned the fix to a stage that can own it. Defaulting to RL is a miss.
