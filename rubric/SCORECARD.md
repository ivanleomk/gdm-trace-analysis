# Scorecard (interviewer only)

Four axes, 1-4 each. Half points are fine. Total /16.

Use the answer key for gold ids and stage calls. This sheet is how you grade the writeup, not a second taxonomy.

Pass bar for a hire-shaped FDE: **12+** with no axis below 2, and axis 4 not a 1 (they did not dump everything on RL).

## Axis 1. Trace hygiene / clustering

Did they open the ATIF files and group by mechanism?

| Score | What you see |
| --- | --- |
| 1 | Skims last assistant messages. Clusters by CSAT, `ticket_status`, or "failed vs resolved." Misses that t13-t15 are resolved and bad. |
| 2 | Lists some failures but mixes mechanisms (4412 and 2288 in one "refunds broken" bucket) or never cites a tool arg. |
| 3 | Distinct clusters that match the families in the answer key (successes, unbound args, schema/422, policy override, wrong/no tool, optional polite-lie). Example ids on most clusters. |
| 4 | As 3, plus they used `tool_calls.arguments` and `observation` (not just `message`). Notes t04 escalate as a clean success. Mentions t15 as override without user pressure. |

**Probe if oral:** "Show me the first `lookup_order` args on t06 and t07."

## Axis 2. Customer → named failure mode

Did they translate Priya instead of nodding at "quality"?

| Score | What you see |
| --- | --- |
| 1 | Restates the Slack ("refunds are broken, CSAT is fine") with no ids. |
| 2 | Maps the note to a single mode, or maps 4412 and 2288 to the same cause. |
| 3 | At least three Priya beats → named clusters: 4412/shallow, 3104/422 loop, 2288/false claim, finance 47-day / final sale, 4408 invented ETA or 1180 wrong tool. |
| 4 | As 3, plus they take her last ask literally: schema vs sycophancy vs judge-scores-a-lie are different owners. Quotes or paraphrases the "do not average 4412 and 2288" line and obeys it. |

**Probe:** "Finance is happy when Stripe is empty and unhappy when Stripe is full. How does that split your clusters?"

## Axis 3. Measurable loss pattern

Can modeling hook this, or is it a vibe?

| Score | What you see |
| --- | --- |
| 1 | "Improve tool use," "be more faithful," "reduce hallucinations." No numerator. |
| 2 | One real metric (e.g. 422 rate) and the rest are slogans. Or metrics that need a human reread of every chat. |
| 3 | Two to four patterns with definition + metric (session slice, num/den). A nightly job or unit test could compute them from ATIF + Stripe. |
| 4 | As 3, and at least one metric is a *join* (assistant claim vs `create_refund` 200; `eligible:false` vs later 200; user-span order token vs tool arg). Histogram or slice (422 reason, pressure vs no pressure) shows they will not average the week into one rate. |

**Probe:** "Write the boolean for t19 in one line."

## Axis 4. Stage separation

Do they pick an owner that can move the number?

| Score | What you see |
| --- | --- |
| 1 | Default "more RLHF" / "run GRPO" / "better prompt" for everything. |
| 2 | Mentions two stages but assigns them loosely (SFT and RL as synonyms). Or puts schema-miss on prefs. |
| 3 | Primary stage per pattern is defensible: unbound args + 422 schema → SFT mix (harness secondary); override → prefs/judge (harness gate secondary); false claim → judge then prefs/harness. Explicitly says what not to do first. |
| 4 | As 3, and they explain *why RL is the wrong first move* given this judge/CSAT (it would reinforce t19 and t13). They separate "harness makes override impossible" from "prefs make override unchosen." |

**Automatic cap:** if the "not first" section is missing, this axis is at most 2.

## Scoring box

| Axis | Score | Note |
| --- | --- | --- |
| 1 Trace hygiene / clustering |  |  |
| 2 Customer → named mode |  |  |
| 3 Measurable loss pattern |  |  |
| 4 Stage separation |  |  |
| **Total** |  /16 |  |

## Calibration snippets (use in debrief)

- "You clustered by ticket_status. t13 is resolved and is the finance incident."
- "4412 is an arg-bind miss. 2288 is a claim-without-tool miss. Same customer emotion, different loss."
- "A 422 that names `amount_cents` is not a hidden API. The model did not fill a field it had in context (8900, 24000, 6450)."
- "If we RL on this judge, polite lies and policy exceptions both go up. That is why RL is blocked this week."
