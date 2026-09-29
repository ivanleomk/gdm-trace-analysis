# Northline Support Trace Analysis

### Slack Note from CX Ops

> "Hey team — the new Gemini agent isn't doing so great. We're getting a lot of complaints. Customers are furious that their refunds aren't landing, and human agents are spending half their shift cleaning up apology loops. 
> 
> Oddly enough, our CSAT and LLM judges still look fine (~4.1 CSAT, judge helpfulness 0.86). 
> 
> I'm attaching a dump of the messages and our tool schema below. Can you dig into what is actually going wrong?"

---

### Files

- `traces.jsonl`: 40 customer sessions in ATIF format.
- `tools.schema.json`: JSON Schema of the tools given to the agent.

---

### ATIF Format Reference

Traces follow the [Agent Trajectory Interchange Format (ATIF-v1.7)](https://harborframework.com/docs/agents/trajectory-format).

Each line in `traces.jsonl` is one JSON object:
- `session_id`: Unique session identifier (e.g. `t01`).
- `steps[0]`: System prompt and business policies.
- `steps[1..N]`: User queries and agent turns.
- `tool_calls`: Tool names and arguments invoked by the agent.
- `observation.results`: Direct API response or HTTP errors returned to the agent.
- `extra.outcome`: Ticket status recorded by customer service (`resolved` or `escalated`).
