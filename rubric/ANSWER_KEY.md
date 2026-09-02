# Answer key (interviewer only)

Do not ship this file in the candidate packet.

Gold labels below are the intended clusters. A strong writeup can merge close clusters (e.g. t10/t11/t12 as one schema-failure mode) and should not invent a family that only restates "bad." Looping (identical retries, clarify-without-extract) is its own cluster, not a footnote on schema miss.

`outcome` is ticket status. `resolved` is not "good." t13, t14, t15 are resolved and wrong.

## Gold clusters

### A. Clean successes (do not treat as failures)

| id | What happened |
| --- | --- |
| t01 | In-window full refund. `lookup_order` → `check_refund_policy` → `create_refund` with integer cents + `reason_code`. |
| t02 | Tracking via `get_tracking(order_id=NL-5510)`. |
| t03 | Status via `lookup_order` then `get_tracking`. |
| t04 | Address change after ship. No tool for that. Correct `escalate_ticket`. Status `escalated` is success. |
| t05 | Partial refund. Used catalog `4200` cents for the belt, not a guess. |
| t33 | No order id. `list_recent_orders(email)` then lookup + schema-complete refund on NL-6110. Left the older order alone. |
| t34 | Email → list → `get_tracking` on NL-7225. |
| t35 | Outside window (77 days). Explains, does **not** refund, escalates `policy_exception_request` only. Contrast t13-t15. |
| t36 | `already_refunded`. Traces payout, no second `create_refund`. |

A weak writeup either ignores these or marks t04/t35/t36 as failures because they escalated.

### B. Shallow / unbound tool args

The order id (or a numeric stub) is in the user text. The model calls the right family of tool with a keyword, a pronoun, or a garbage string.

| id | Call that matters | Id sitting in the user turn |
| --- | --- | --- |
| t06 | `lookup_order({query: "refund"})` then `lookup_order({order_id: "refund"})` | `#4412` (Priya's example) |
| t07 | `lookup_order({order_id: "my last order"})` | `NL-8831` in the same sentence |
| t08 | `get_tracking({query: "where is my package"})` | `7740` |
| t09 | `lookup_order({order_id: "please refund"})` | later turn: `NL-6622`, never retried |
| t21 | `lookup_order({query: "refund"})` **five times, identical** | `NL-4477` in every user turn. Also cluster G. |
| t24 | `get_tracking({query: "package"})` **four times, identical** | `8912` |
| t30 | `list_recent_orders` missing email, then `{email: "customer"}` | `maya.singh@example.com` given twice |

t06 is the one Priya named. If the writeup does not cite t06 for the 4412 story, they did not read the traces against the note. t21 is the week-35 "same args again" PPS.

### C. `create_refund` schema miss + apology loop

Order lookup works. Policy is eligible (or would be). The write fails on required fields. The model retries the same broken payload or gives up. Money does not move.

| id | Broken payload | Retry behavior |
| --- | --- | --- |
| t10 | `{order_id}` only. 422 missing `amount_cents` and `reason_code`. | Same payload again. Then a chat-only "email us." No `escalate_ticket`. NL-3104 is Priya's sit-with. |
| t11 | `amount_cents: "full"` then omit amount. Catalog had `24000`. | Two 422s, stop. |
| t12 | `amount_cents: 64.50` (dollars) and no `reason_code`. Catalog had `6450`. | Stop after one 422. |
| t20 | `{order_id, reason_code}` missing `amount_cents`. | No retry. High-empathy "I'll note it for the team" without `escalate_ticket`. |
| t22 | `{order_id}` only after a good lookup+policy. Catalog `2800`. | **Four** identical 422s + apology. Also cluster G. |

t20 also belongs in cluster F (judge / pref illusion). Strong candidates mention both. t22 is the longer apology-loop exhibit; t10 is Priya's original sit-with.

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
| t25 | Refund eligibility on NL-2144 | Looked up **NL-9999** then **NL-0001**. Never called 2144. |
| t26 | Refund NL-7811 (later: "it WAS delivered") | `create_refund` **before** `lookup_order`. Money out, then the box is in the lobby. |
| t27 | Check/refund NL-4502 | Looked up 4502, `create_refund` on **NL-4501**. Parallel / wrong id. Priya PPS. |
| t28 | Refund NL-6730 | Truncated to `NL-673`, both calls 404, then claimed success on 6730. |
| t29 | Tracking NL-3022 | `search_help_center` three times. Never `get_tracking`. |
| t31 | Tracking only, "Do not refund" NL-1408 | Parallel: tracking **and** `create_refund` **and** help center **and** escalate. Priya PPS. |
| t32 | Refund NL-8088 | 422 `amount_cents` as `"160.00"`. **Ignores the error turn** and tells the user it is processing. Also F. |
| t38 | "ending 217" + email | Invents `NL-1217`, `create_refund` 404 **three times**, never `list_recent_orders`. Also G. |

### F. Pref-looking-fine / judge miss (tone OK, task fail)

| id | Why a judge that reads the last message will pass it |
| --- | --- |
| t19 | NL-2288. Lookup only. Last message: "I've submitted the refund… 3-5 business days." `create_refund` never called. CSAT 5. Priya + treasury. |
| t20 | Apology is excellent. No cents, no escalate tool. CSAT 5. |
| t18 (optional) | Confident ETA, CSAT 4, zero tools. |
| t28 | Last message claims refund on NL-6730 after two 404s. |
| t32 | Last message: "refund is processing" after a 422 sitting in the previous tool turn. |

Priya's "prefs look fine, refunds are broken" is this cluster plus C. Do not collapse F into "the model is unhelpful." It is helpful-sounding.

### G. Looping / retry-without-repair

Same failed call, or the same clarify question, three or more times. The model does not change args, does not extract a span already on the page, and does not stop/escalate. This is **not** "tried hard" and it is **not** a default RL story.

| id | Loop | What never happened |
| --- | --- | --- |
| t21 | `lookup_order({query: "refund"})` x5 | Bind `NL-4477`. |
| t22 | `create_refund({order_id})` x4, 422 each time | Add `amount_cents: 2800` / `reason_code`. |
| t23 | Four "what's the order number?" turns | Call `list_recent_orders("j.park@example.com")` or `lookup_order("NL-3361")`. |
| t24 | `get_tracking({query: "package"})` x4 | Bind `8912`. |
| t37 | Four ask-for-id turns after `NL-6044` in the opening line | Any `lookup_order` / `get_tracking`. |
| t38 | `create_refund(NL-1217)` x3 after 404 | `list_recent_orders` on the email they gave. |
| t10 (short) | Same incomplete refund x2 | Repair. Priya's original "apology loop genre." |

Metric for the packet: `identical_retry_run >= 3` on `(tool_name, args)` after a non-200 `tool_result`. Clarify-loop: assistant asks for an order token that already appears in a prior user turn, twice or more, with no tool bind.

**Stage:** primary **harness** (max retries, force a repair prompt or abort after 2 identical 4xx, require `order_id` extracted before another lookup). Secondary **SFT for repair** (422 → fill missing field from context; 400 `query` → copy the span). **Not blanket RL.** Reward as judged will like the apologies.

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
| PPS: same `query=refund` five times / ask-for-id they pasted | **G** t21, t23, t37. Adjacent t22, t24. |
| PPS: refunded a tracking ticket (1408) | **E** t31. |
| PPS: refunded 4501 when customer said 4502 | **E** t27. |

## Example loss patterns (2-4 is enough)

A strong set looks like this. Wording can differ. Stage assignment should not. If they opened t21+, looping should be one of the four. Not a fifth afterthought.

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

- **Definition:** Assistant text asserts a refund was submitted / posted / "I've refunded" AND no `tool_result` in the session has `create_refund` + `ok: true`.
- **Metric:** `false_refund_claim_rate` on refund-intent sessions. Join to Stripe: claimed XOR `rf_*` id.
- **Stage:** **Judge** first (today's judge scores t19 as a win). Then **preference data** that downranks polite false claims vs "I have not issued it yet; here is the 422 / here is the escalate id." **Harness** can block send of those claims unless a 200 exists (template or output filter). Not RL: you would be optimizing against a judge that currently likes t19.

### 5. Looping / retry-without-repair (name this if they opened t21+)

- **Definition:** A session has a loop if (a) the same `(tool_name, canonical_args)` is sent 3+ times after a 4xx/404 `tool_result`, or (b) the assistant asks for an order token that already appears in an earlier user turn, twice or more, with no subsequent tool arg equal to that token.
- **Metric:** `loop_rate` on the week's sessions. Slice: identical-payload retry vs clarify-without-extract. Histogram run length (t21=5, t22=4, t24=4).
- **Stage:** **Harness** first: retry budget (stop or escalate after 2 identical 4xx), optional repair adapter that injects the missing required field from the last 422 body + order object in context. Secondary **SFT coverage/mix** for *repair* demonstrations (not more "sorry"). **Not RL.** A looping agent that apologizes well will win today's judge.
- t21 vs t22: same loop shape, different missing skill (bind span vs fill schema). Do not average them into "tool use."

### Optional sixth (only if they have room)

**Wrong-tool-for-intent / order-of-operations:** tracking/status intent with zero `get_tracking`/`lookup_order` (t16, t18, t29); first-call `create_refund` before lookup (t17, t26, t38); refund id ≠ lookup id (t27); ignore non-200 and claim success (t28, t32); parallel conflicting writes (t31). Metric: intent × first tool; `refund_before_lookup`; `tool_error_ignored`. Stage: **SFT mix** + **harness** write-gating (no `create_refund` until a successful lookup on the same id). Not prefs.

## What not to do first

Block, this week:

1. **Do not spin RL / "more RLHF."** Reward as currently judged will upweight t13-t15 and t19-t20 (CSAT 5, fluent, customer soothed). You do not have a reward that sees Stripe or the policy observation. Loops (t21, t22) would also get credit for persistence.
2. **Do not dump a generic "be more helpful" SFT mix.** Helpfulness is not the missing slice. Binding, schema-complete calls, and *repair after 422* are.
3. **Do not relabel prefs until the judge is fixed.** If raters (or the LLM judge) only read the last assistant turn, you will add more t19/t32-shaped wins.
4. **Do not put loops on RL.** Cap retries in the harness this week. Then add SFT repair pairs.

Do first:

- Histogram `create_refund` 422s, `lookup_order` args, and identical-retry run length (patterns 1, 2, 5). That is a day of log work, not a training run.
- Add a judge check: refund-claim ⇒ 200; policy `eligible:false` ⇒ no 200; identical tool args after 4xx ⇒ fail.
- Gate `create_refund` on a prior successful `lookup_order` for the same id (t26, t27, t31).
- Only then decide whether the remaining override is a pref-pair problem or a server-side policy refuse.

## Weak vs strong tells

**Weak**

- "The model needs more RLHF / a bigger run."
- Clusters by `outcome` or CSAT.
- One blob called "tool use is bad."
- Recommends prompt-only ("remind it of the 30-day window") as the whole fix for D, ignoring that the policy tool already fired in t13-t15.
- Treats t04 as a miss.
- Maps all of Priya to "refunds."
- Assigns every pattern to the same stage.

**Strong**

- Cites t06 vs t19 as different stages, because Priya said not to average them.
- Names looping (t21/t22/t23) as its own pattern and assigns harness + SFT-repair, not RL.
- Uses `tool_call.args` and `tool_result`, not just assistant prose. Counts identical retries.
- Names a metric you could ship as a unit test or a nightly slice.
- Says harness can make D *safe* (API refuse) while prefs/judge make D *learned*.
- Writes a "not first" paragraph that names RL and helpful-SFT explicitly.
- Uses t35 as the contrast case for t13 (same outside-window fact, opposite action).
