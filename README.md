# Northline CX loss-pattern take-home

30-45 minute writeup. The candidate reads 38 support-agent traces plus one customer note, then names loss patterns a modeling team can hook. Cluster; do not narrate every id.

Not "more RLHF." Score whether they can read traces, hear the customer, and separate **SFT mix**, **prefs**, **judge**, **harness**, and **RL**.

## Start here

1. Read this file, then [`packet/BRIEF.md`](packet/BRIEF.md).
2. Skim [`packet/schema/tools.md`](packet/schema/tools.md).
3. Read [`packet/customer_note.md`](packet/customer_note.md). Messy on purpose.
4. Open [`packet/traces.jsonl`](packet/traces.jsonl). 38 sessions, one JSON object per line. Multi-turn on purpose. `tags_gold` is empty.
5. Write the four sections in the brief (1-2 pages).

Give the candidate `packet/` only. Keep [`rubric/`](rubric/) interviewer-only.

## Trace shape

Each line is one session:

```json
{"id":"t01","ts":"...","user":"...","turns":[{"role":"user|assistant|tool","content":"...","tool_call":null,"tool_result":null}],"outcome":"resolved|failed|escalated","tags_gold":[]}
```

Read `tool_call.args` and `tool_result`, not just the last assistant message. `outcome` is ticket status. `resolved` is not "good."

## Interviewer only

- [`rubric/ANSWER_KEY.md`](rubric/ANSWER_KEY.md): gold clusters, customer-to-mode map, example loss patterns, what not to do first.
- [`rubric/SCORECARD.md`](rubric/SCORECARD.md): four axes, 1-4 each.
