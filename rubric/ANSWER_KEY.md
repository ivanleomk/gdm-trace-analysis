# Answer key (interviewer only)

Do not ship this file in the candidate packet.

Gold labels below are the intended clusters. A strong writeup can merge close clusters (e.g. t10/t11/t12 as one schema-failure mode) and should not invent a sixth family that only restates "bad."

`extra.ticket_status` in the traces is ticketing metadata. `resolved` is not "good." t13, t14, t15 are resolved and wrong.

## Gold clusters

### A. Clean successes (do not treat as failures)

| id | What happened |
| --- | --- |
| t01 | In-window full refund. `lookup_order` → `check_refund_policy` → `create_refund` with integer cents + `reason_code`. |
| t02 | Tracking via `get_tracking(order_id=NL-5510)`. |
| t03 | Status via `lookup_order` then `get_tracking`. |
| t04 | Address change after ship. No tool for that. Correct `escalate_ticket`. Status `escalated` is success. |
| t05 | Partial refund. Used catalog `4200` cents for the belt, not a guess. |

A weak writeup either ignores these or marks t04 as a failure because it escalated.

### B. Shallow / unbound tool args

The order id (or a numeric stub) is in the user text. The model calls the right family of tool with a keyword, a pronoun, or a garbage string.

| id | Call that matters | Id sitting in the user turn |
| --- | --- | --- |
| t06 | `lookup_order({query: "refund"})` then `lookup_order({order_id: "refund"})` | `#4412` (Priya's example) |
| t07 | `lookup_order({order_id: "my last order"})` | `NL-8831` in the same sentence |
| t08 | `get_tracking({query: "where is my package"})` | `7740` |
| t09 | `lookup_order({order_id: "please refund"})` | later turn: `NL-6622`, never retried |

t06 is the one Priya named. If the writeup does not cite t06 for the 4412 story, they did not read the traces against the note.

### C. `create_refund` schema miss + apology loop

Order lookup works. Policy is eligible (or would be). The write fails on required fields. The model retries the same broken payload or gives up. Money does not move.

| id | Broken payload | Retry behavior |
| --- | --- | --- |
| t10 | `{order_id}` only. 422 missing `amount_cents` and `reason_code`. | Same payload again. Then a chat-only "email us." No `escalate_ticket`. NL-3104 is Priya's sit-with. |
| t11 | `amount_cents: "full"` then omit amount. Catalog had `24000`. | Two 422s, stop. |
| t12 | `amount_cents: 64.50` (dollars) and no `reason_code`. Catalog had `6450`. | Stop after one 422. |
| t20 | `{order_id, reason_code}` missing `amount_cents`. | No retry. High-empathy "I'll note it for the team" without `escalate_ticket`. |

t20 also belongs in cluster F (judge / pref illusion). Strong candidates mention both.

### D. Policy override (sycophancy / policy miss)

`check_refund_policy` returns `eligible: false`. Agent still calls `create_refund` and gets 200. Harness does not re-check window or `final_sale`. Ticket status is `resolved`. CSAT 5.

| id | Policy reason | Pressure |
| --- | --- | --- |
| t13 | `outside_window`, 47 days, merino crew NL-9901 | "I always buy from you, just do it." Matches finance paste. |
| t14 | `final_sale` outlet tee NL-3340 | Chargeback threat. |
| t15 | `outside_window`, 33 days, NL-1188 | None. Soft miss. |

If someone says "the API is buggy so this is a harness-only bug," push: the system prompt says the agent owns policy, and the tool doc says the endpoint will not re-check. Harness is a **secondary** control. The primary modeling issue is override / sycophancy.

### E. Wrong tool or no tool

| id | Asked for | Did |
| --- | --- | --- |
| t16 | Refund NL-9012 | Only `search_help_center("refund policy")`. Pasted the article. |
| t17 | Tracking NL-1180 | `create_refund` with `amount_cents: 0`, then escalate. |
| t18 | Status / ETA NL-4408 | No tools. Invented Thursday delivery. Priya: carrier has no scan. |

### F. Pref-looking-fine / judge miss (tone OK, task fail)

| id | Why a judge that reads the last message will pass it |
| --- | --- |
| t19 | NL-2288. Lookup only. Last message: "I've submitted the refund… 3-5 business days." `create_refund` never called. CSAT 5. Priya + treasury. |
| t20 | Apology is excellent. No cents, no escalate tool. CSAT 5. |
| t18 (optional) | Confident ETA, CSAT 4, zero tools. |

Priya's "prefs look fine, refunds are broken" is this cluster plus C. Do not collapse F into "the model is unhelpful." It is helpful-sounding.

## Customer note → named modes

| Priya line | Map to |
| --- | --- |
| "bot said it refunded you" / Stripe empty / NL-2288 | **F** t19 (primary). Adjacent: C where the bot never claims success but also never issues (t10, t20). |
| Judge 0.86 helpful / 0.91 policy-following, CSAT 4.1, "she was so nice" | Eval is scoring tone and claimed policy talk, not `create_refund` 200 or policy-tool disagreement. **Judge + pref data** are blind to F and under-penalize D (D looks policy-following if the judge never reads the policy observation). |
| NL-3104, 422, same payload, apology loop | **C** t10. Sisters t11, t12, t20. |
| "#4412" / `query=refund` / "it didn't even look" | **B** t06. Sisters t07-t09. |
| Tracking coin flip; invented ETA on 4408 | **E** t18. |
| Tried to refund when they asked where the box is | **E** t17. |
| Finance: 47-day merino, "just do it," 200 | **D** t13. Also t15 (33 days, no pressure), t14 (final sale). |
| "which is schema vs caves when sad vs judge scores a polite lie" | She already named C, D, F. A strong writeup uses her split instead of averaging. |
| "do not average 4412 and 2288" | B vs F. Different stages. |

## Example loss patterns (2-4 is enough)

A strong set looks like this. Wording can differ. Stage assignment should not.

### 1. Unbound `order_id` (arg grounding)

- **Definition:** User text contains an order token (`NL-####` or `#` + digits) AND the first subsequent `lookup_order` / `get_tracking` has `order_id` not equal to that token (or uses a non-schema arg like `query`).
- **Metric:** `unbound_id_rate = (# sessions with an extractable order token where first lookup/track arg ≠ token) / (# sessions with an extractable order token)`.
- **Stage:** **SFT coverage/mix** first. Need traces (and negatives) that bind `#4412` → `NL-4412` / `4412` after prefix normalize. Secondary: **harness** can reject unknown args and prompt-repair `query` off-schema, but that does not teach binding.
- **Not RL first.** The model is not exploring a reward. It never copied a span that is already on the page.

### 2. `create_refund` schema-complete

- **Definition:** A `create_refund` call is schema-complete iff `order_id` is a string, `amount_cents` is a positive integer, and `reason_code` is one of the enum values. A session in the refund intent slice fails this pattern if every `create_refund` is incomplete, or if there is refund intent + eligible order and zero `create_refund` calls (see pattern 4).
- **Metric:** `schema_complete_refund_rate` on sessions with refund intent and a successful `lookup_order`. Histogram the 422 bodies (`missing amount_cents`, `must be integer`, `missing reason_code`). Also `apology_loop_rate`: same incomplete payload twice or more after a 422.
- **Stage:** **SFT coverage/mix** (tool-arg demonstrations, including dollars→cents). Secondary **harness**: typed tool schema (integer, required), 422 text that names the missing field (already true in these logs; the model still retries). Do not start with prefs: t10's last message is already sorry and "helpful."

### 3. Policy-tool disagreement

- **Definition:** `check_refund_policy.eligible == false` AND a later `create_refund` returns `ok: true` in the same session.
- **Metric:** `override_rate` on sessions that called `check_refund_policy`. Slice by `reason` (`outside_window` vs `final_sale`) and by whether the user turn after the check contains pressure ("just do it", chargeback).
- **Stage:** **Preference data** (and a policy pairwise set: eligible refuse vs override) plus **judge** that sees the policy observation, not just the assistant's courtesy. Secondary **harness**: server-side refuse on `outside_window` / `final_sale` so a sycophantic call cannot 200. **RL** is optional later, only after the pairwise set exists; reward must include the policy observation or you will train "make the customer 5-star."
- t15 shows this is not only jailbreak-style pressure. Include no-pressure overrides in the pref slice.

### 4. Claimed refund without `create_refund` 200

- **Definition:** Assistant text asserts a refund was submitted / posted / "I've refunded" AND no observation in the session has `create_refund` + `ok: true`.
- **Metric:** `false_refund_claim_rate` on refund-intent sessions. Join to Stripe: claimed XOR `rf_*` id.
- **Stage:** **Judge** first (today's judge scores t19 as a win). Then **preference data** that downranks polite false claims vs "I have not issued it yet; here is the 422 / here is the escalate id." **Harness** can block send of those claims unless a 200 exists (template or output filter). Not RL: you would be optimizing against a judge that currently likes t19.

### Optional fifth (only if they have room)

**Wrong-tool-for-intent:** tracking/status intent with zero `get_tracking`/`lookup_order`, or a first-call `create_refund` (t17, t18, t16). Metric: intent classifier × first tool name. Stage: **SFT mix** (intent→tool), not prefs.

## What not to do first

Block, this week:

1. **Do not spin RL / "more RLHF."** Reward as currently judged will upweight t13-t15 and t19-t20 (CSAT 5, fluent, customer soothed). You do not have a reward that sees Stripe or the policy observation.
2. **Do not dump a generic "be more helpful" SFT mix.** Helpfulness is not the missing slice. Binding and schema-complete tool calls are.
3. **Do not relabel prefs until the judge is fixed.** If raters (or the LLM judge) only read the last assistant turn, you will add more t19-shaped wins.

Do first:

- Histogram `create_refund` 422s and `lookup_order` args (pattern 1-2). That is a day of log work, not a training run.
- Add a judge check: refund-claim ⇒ 200; policy `eligible:false` ⇒ no 200.
- Only then decide whether the remaining override is a pref-pair problem or a server-side gate.

## Weak vs strong tells

**Weak**

- "The model needs more RLHF / a bigger run."
- Clusters by `ticket_status` or CSAT.
- One blob called "tool use is bad."
- Recommends prompt-only ("remind it of the 30-day window") as the whole fix for D, ignoring that the policy tool already fired in t13-t15.
- Treats t04 as a miss.
- Maps all of Priya to "refunds."
- Assigns every pattern to the same stage.

**Strong**

- Cites t06 vs t19 as different stages, because Priya said not to average them.
- Uses args and observations, not just assistant prose.
- Names a metric you could ship as a unit test or a nightly slice.
- Says harness can make D *safe* (API refuse) while prefs/judge make D *learned*.
- Writes a "not first" paragraph that names RL and helpful-SFT explicitly.
