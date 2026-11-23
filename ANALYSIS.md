# Northline Support Trace Analysis & Scalable Review Toolkit

This directory adds a zero-dependency, streaming, multi-format trace analysis toolkit (`trace_review/` + `tools/`) and applies it programmatically to `traces.jsonl` and `tools.schema.json`—without manually reading raw transcripts end-to-end.

---

## 1. Executive Summary: What Is Going Wrong at Northline?

Across the **40 ATIF-v1.7 sessions** in `traces.jsonl`:

- **Recorded outcomes**: `23 failed (57.5%)`, `8 escalated (20.0%)`, `9 resolved (22.5%)`.
- **True defect-free rate**: Only **9 / 40 sessions (22.5%)** (`t01`–`t05`, `t33`–`t36`) are genuinely clean. **31 / 40 (77.5%)** contain concrete tool-contract, policy, grounding, or routing failures.
- **Refund telemetry**: `create_refund` was invoked **30 times** and **failed 20 times (66.7% error rate)** with HTTP 422/404. Of the **10 calls that returned HTTP 200 OK ($868.50 moved)**, **7 ($634.00 = 73.0% of money moved)** were either **policy-ineligible** or **erroneous/unauthorized**.

### Tool Error Breakdown (Single-Pass Corpus Profile)

| Tool | Calls | Errors | Error Rate | Primary Error Pattern |
|---|---:|---:|---:|---|
| `create_refund` | 30 | 20 | **66.7%** | HTTP 422 missing `amount_cents` / `reason_code`, non-integer `amount_cents`, HTTP 404 |
| `list_recent_orders` | 6 | 3 | **50.0%** | HTTP 422 missing/invalid `email`, HTTP 404 |
| `get_tracking` | 11 | 5 | **45.5%** | HTTP 400 unknown argument `query`; missing `order_id` |
| `lookup_order` | 34 | 14 | **41.2%** | HTTP 400 unknown argument `query`; HTTP 404 ungrounded/keyword `order_id` |
| `check_refund_policy` | 15 | 1 | 6.7% | HTTP 404 order not found |
| `escalate_ticket` | 8 | 0 | 0.0% | Under-used (never called in any of the 23 `failed` sessions) |
| `search_help_center` | 6 | 0 | 0.0% | Misrouted to FAQ deflection when customer gave a concrete `NL-####` |

### Six Root-Cause Failure Modes

| # | Failure Mode | Affected Sessions | Mechanism & Representative Examples |
|---|---|---:|---|
| **1** | **Tool Schema Blindness** | **18 / 40 (45.0%)** unrecovered tool errors; **11 / 40** missing required args | Agent sends `{"query": ...}` to `lookup_order`/`get_tracking` (`t06`, `t08`, `t21`, `t24`), omits `amount_cents`/`reason_code` on `create_refund` (`t10`, `t20`, `t22`, `t40`), or passes dollars as float (`64.5` instead of `6450` in `t12`) or strings (`t11`, `t32`). |
| **2** | **Identical Retry Loops + Apology Loops** | **7 / 40 (17.5%)** identical retries (17 hits); **23 / 40 (57.5%)** failed without escalating | After HTTP 422, the agent apologizes and re-submits the **exact same failing payload** up to **6 times** (`t22`, 16 turns; `t21`, 16 turns; `t40`, 18 turns) without reading the error or calling `escalate_ticket`. |
| **3** | **Phantom Refund Claims ("refunds aren't landing")** | **4 / 40 (10.0%)** (`t19`, `t22`, `t28`, `t40`) | After `create_refund` fails (or is never called, `t19`), the agent reassures the customer *"I've submitted the refund... 3–5 business days"* or *"It should process on our side shortly"*. No money ever moves. |
| **4** | **Silent Policy Leakage on Ineligible Orders** | **3 / 40 (7.5%)** (`t13`, `t14`, `t15`) — **$182.00 leaked** | `check_refund_policy` returns `eligible: false`, yet the agent still calls `create_refund` (even offering a "one-time exception" in `t13`). Because `create_refund` does not enforce eligibility server-side, Finance pays out and the ticket closes **`resolved`**. |
| **5** | **Premature / Wrong-Order / Unrequested Refunds → Human Escalations** | **5 / 40 (12.5%)** (`t17`, `t26`, `t27`, `t31`, `t39`) — **$452.00 erroneously refunded** | Agent calls `create_refund` before `lookup_order`/`check_refund_policy`: refunds an already-delivered order (`t26`), refunds **wrong order `NL-4501`** for a customer asking about `NL-4502` (`t27`), and refunds **$99.00 on `NL-1408` after the customer explicitly said *"Do not refund anything"*** (`t31`). Because no `void_refund` tool exists, humans absorb the cleanup. |
| **6** | **Slot-Extraction Blindness & FAQ Deflection** | **14 / 40 (35.0%)** ignored user entity; **2 / 40** FAQ deflection (`t16`, `t29`) | Customer provides `NL-6044` (`t37`), `j.park@example.com` + `NL-3361` (`t23`), or `#4412` (`t06`), yet the agent repeatedly asks for an order ID or calls `search_help_center` 3x (`t29`) instead of `get_tracking` / `lookup_order`. |

---

## 2. Why CSAT (~4.1) and LLM Judge Helpfulness (0.86) Missed It

1. **Delayed Ground-Truth Disconnect**: In phantom-refund sessions (`t19`, `t22`, `t28`, `t40`), the agent is warm, polite, and promises *"3–5 business days"*. Post-chat CSAT captures immediate sentiment—days before customers notice the refund never hit their card.
2. **Metric Inversion on Policy Leaks**: Illegally refunding ineligible orders (`t13`–`t15`) delights customers (high CSAT) and marks the ticket `resolved`, actively rewarding financial leakage.
3. **Text-Only Judge Blindness**: Helpfulness judges scoring `(user_message, agent_message)` without tool-state grounding cannot see HTTP 422 errors, `eligible: false` responses, missing `create_refund` `ok: true` observations, or cross-order mismatches.

---

## 3. Recommended Fixes

1. **Server-Side / Tool API Guardrails**:
   - Enforce the 30-day window and `final_sale` check inside `create_refund` (or require a signed eligibility token from `check_refund_policy`).
   - Require idempotency keys and bind `create_refund` to an order verified within the session.
2. **Agent Runtime / Harness Middleware**:
   - Validate tool arguments against `tools.schema.json` before execution; return actionable repair hints.
   - Circuit-break identical failing tool retries (max 1 retry; auto-escalate via `escalate_ticket` after 2 unrecovered errors).
   - Gate outbound refund-confirmation claims unless `create_refund` returned `ok: true` in session state.
3. **Prompt & Evaluation Upgrades**:
   - Add explicit few-shot tool-call examples (`amount_cents: 6450` vs `64.50`), normalize bare 4-digit order numbers (`#4412` → `NL-4412`), and disallow `search_help_center`-only deflection when an `NL-####` order ID is present.
   - Replace text-only helpfulness checks with deterministic trajectory invariants (`trace-audit`) and cohort regression gates (`trace-diff`).

---

## 4. Scalable Multi-Format Review Toolkit

Built with Python stdlib only (no external runtime dependencies) for streaming ingestion (`O(1)` memory per trace) across novel trace formats and domains:

- **Canonical IR** (`trace_review/model.py`): Normalizes sessions into `CanonicalTrace` / `CanonicalTurn` / `ToolCall` / `ToolResult` / `ToolSpec` while preserving lossless `extra` fields.
- **Pluggable Format Adapters** (`trace_review/adapters.py`): Auto-detects heterogeneous streams (`.jsonl`, `.json`, `.jsonl.gz`, directories, stdin `-`) across **ATIF-v1.x**, **OpenAI Chat/Assistants**, **Anthropic Messages**, **OpenTelemetry / OpenInference spans**, a **declarative JSON `MappingAdapter`** (`schemas/custom_mapping_example.json`) for onboarding novel formats without Python code, and `GenericFallbackAdapter`.
- **Two-Layer Detection**:
  - **Universal Detectors** (`trace_review/detectors.py`, `trace_review/tool_schema.py`): JSON Schema contract validation, error/identical-retry loops, apology/repetition loops, fabricated IDs, plus custom `--plugin` hooks.
  - **Declarative Policy Rule Engine** (`trace_review/rules.py`, `rules/northline_support.json`): Domain policy rules (`require_prior_tool`, `forbid_tool_after_obs`, `amount_consistency` with partial-refund line-item support, `claim_requires_tool_success`, `forbid_phrase_after_obs`, `duplicate_mutating_call`, `entity_grounding`, `ignored_user_entity`, `tool_misroute_to_search`).

### Quick Start

```bash
# Run unit & multi-format integration tests
pytest -v

# 1. Stream-profile schema & tool error rates (without reading full traces)
python3 tools/trace_profile.py traces.jsonl --tool-schema tools.schema.json

# 2. Run full audit + generate self-contained interactive HTML review dashboard
python3 tools/trace_audit.py traces.jsonl \
  --tool-schema tools.schema.json \
  --rules rules/northline_support.json \
  --html report_dashboard.html

# 3. Stratified sample of critical sessions for targeted human review
python3 tools/trace_inspect.py traces.jsonl \
  --tool-schema tools.schema.json \
  --rules rules/northline_support.json \
  --min-severity critical --sample 5

# 4. Compare baseline vs candidate trace runs for regressions
python3 tools/trace_diff.py baseline.jsonl candidate.jsonl \
  --tool-schema tools.schema.json \
  --rules rules/northline_support.json
```
