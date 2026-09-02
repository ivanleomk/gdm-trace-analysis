# Northline CX traces (week 34–35)

Hey — dumping what we have. Prefer you read the raw chats + the tool schema; I do not have time for a cleaned taxonomy.

**Format:** `traces.jsonl` is one [ATIF](https://www.harborframework.com/docs/agents/trajectory-format) trajectory per line (`ATIF-v1.7`). First step is `source: "system"` (agent policy). Tools are on `agent.tool_definitions` and mirrored in `tools.schema.json`.

Validate locally:

```bash
uv run --with harbor python validate_atif.py
```

**Symptom:** CSAT / prefs / LLM judge look fine (CSAT ~4.1, judge helpful 0.86 / policy 0.91). Refunds are not landing. Floor keeps cleaning apology loops.

**Ask:** Open the ATIF traces + `tools.schema.json`. Tell us which failures are schema/args, which are policy cave-ins, which are polite lies the judge scores as wins, and which are pure retry loops. Do not average them. Do not lead with "more RL."

Start with NL-4412 and NL-2288 if you only have bandwidth for two.

— Priya (CX)
