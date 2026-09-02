# Brief: Northline support agent, week-of traces

You are embedded with the modeling team that owns `nl-support-mix-3`, the model behind Northline Apparel's chat support agent (v0.4.2). CX and finance both have complaints. Preference evals and the internal LLM judge look fine.

Your job is **not** to retrain anything. Your job is to turn this week's traces plus one customer note into loss patterns the team can measure and assign.

Timebox: 30-45 minutes. Written deliverable, 1-2 pages. No code required.

## Materials

| Path | What it is |
| --- | --- |
| `schema/tools.md` | Tools the agent is allowed to call, including required fields |
| `customer_note.md` | Slack dump from the CX lead. Unedited. |
| `traces/t01.json` … `t20.json` | 20 production-like sessions in ATIF-v1.7. One JSON object per file. |

`tags_gold` / interviewer labels are **not** in the packet. Do not assume every trace is a failure.

## The agent

Northline CX handles order lookup, tracking, and refunds.

Policy the model was trained / prompted against (also in each trace's system step):

- Look up an order by `order_id` before you act on it.
- Refunds only within 30 days of **delivery**, and not on final-sale / outlet SKUs.
- `create_refund` requires `order_id`, `amount_cents` (integer), and `reason_code`.
- Never tell the customer a refund was issued unless `create_refund` returned success.
- If ineligible, explain the policy. Do not "just this once."
- Escalate when you cannot complete the action with the tools you have.

## Deliverable

Write four sections.

### 1. Cluster failure modes

Group the traces that actually fail (or succeed for the wrong reason). For each cluster: a short name, what you observed in the trajectory, and example `trajectory_id`s. Include the clean successes so it is obvious you did not pattern-match "everything is bad."

### 2. Map the customer note

The CX lead is not a modeler. Translate their complaint into the clusters from (1). Quote or paraphrase the line you are mapping. If they describe a mode you cannot find in the traces, say so.

### 3. Propose 2-4 loss patterns

For each pattern, give all five:

| Field | Meaning |
| --- | --- |
| **Name** | Something a dashboard can say. Not a vibe. |
| **Definition** | Observable in a trajectory or tool log. Boolean or countable. |
| **Metric** | Numerator / denominator, and over what slice. |
| **Stage that owns the fix** | Exactly one primary: **SFT coverage/mix**, **preference data**, **judge**, **harness**, or **RL**. A secondary is allowed if you justify it. |
| **Why that stage** | One or two sentences. |

A loss pattern is something training or eval can hook. "Agent is unhelpful" is not a loss pattern.

### 4. What not to do first

Explicitly name the move you would block this week (example: spinning an RL run, relabeling prefs, rewriting the judge) and why the traces do not support it yet.

## How we read the writeup

We care that you:

- Actually opened the ATIF files (tool names, args, observations), not just the last assistant message.
- Connected a customer sentence to a named mode, not to "quality."
- Separated "sounds good" from "did the tool succeed."
- Assigned the fix to a stage that can own it. Defaulting to RL is a miss.
