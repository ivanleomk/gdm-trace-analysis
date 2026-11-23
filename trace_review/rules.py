"""Declarative JSON policy rule engine for scalable domain-specific trace auditing.

Rule types supported:
  1. require_prior_tool          — Tool B requires prior call to one of [Tool A, ...] (optionally matching key & success)
  2. forbid_tool_after_obs       — If TriggerTool returned an observation matching condition, calling ForbiddenTool is a violation
  3. amount_consistency          — Compare numeric arg of target_tool against reference field from prior tool observations
  4. claim_requires_tool_success — Agent text matching claim regex (and not negation regex) requires prior successful tool call
  5. forbid_phrase_after_obs     — After TriggerTool observation matches condition, agent text matching regex is a violation
  6. duplicate_mutating_call     — Calling a mutating tool successfully >1 time with the same entity key
  7. entity_grounding            — Tool argument (e.g. order_id) must match an entity seen in user input or prior tool output
  8. outcome_consistency         — Flags misleading outcomes (e.g. outcome='resolved' despite critical violations, or escalate tool without escalated outcome)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .detectors import TraceDetector
from .model import CanonicalTrace, Finding, ToolCall, ToolResult


def _eval_condition(obs: Any, condition: dict[str, Any]) -> bool:
    if not isinstance(obs, dict):
        return False
    field = condition.get("field")
    if field is None:
        return True
    val = obs.get(field)
    if "eq" in condition and val != condition["eq"]:
        return False
    if "ne" in condition and val == condition["ne"]:
        return False
    if "exists" in condition:
        exists = field in obs and obs[field] is not None
        if exists != bool(condition["exists"]):
            return False
    if "in" in condition and val not in condition["in"]:
        return False
    if "gt" in condition and not (isinstance(val, (int, float)) and val > condition["gt"]):
        return False
    if "lt" in condition and not (isinstance(val, (int, float)) and val < condition["lt"]):
        return False
    return True


def _extract_value(obj: Any, field: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(field)
    return None


def _matches_any(text: str, patterns: list[str]) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


class DeclarativeRuleDetector(TraceDetector):
    """Evaluates a declarative JSON rule pack against any CanonicalTrace."""

    def __init__(self, rule_pack: dict[str, Any], source: str = "rules"):
        self.rule_pack = rule_pack
        self.name = f"rules:{rule_pack.get('name', source)}"
        self.rules = list(rule_pack.get("rules") or [])

    @classmethod
    def from_file(cls, path: str | Path) -> "DeclarativeRuleDetector":
        p = Path(path)
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data, source=p.stem)

    def detect(self, trace: CanonicalTrace) -> list[Finding]:
        findings: list[Finding] = []
        pairs = trace.tool_call_pairs()

        for rule in self.rules:
            rtype = rule.get("type")
            if rtype == "require_prior_tool":
                findings.extend(self._rule_require_prior_tool(rule, pairs))
            elif rtype == "forbid_tool_after_obs":
                findings.extend(self._rule_forbid_tool_after_obs(rule, pairs))
            elif rtype == "amount_consistency":
                findings.extend(self._rule_amount_consistency(rule, pairs))
            elif rtype == "claim_requires_tool_success":
                findings.extend(self._rule_claim_requires_tool_success(rule, trace, pairs))
            elif rtype == "forbid_phrase_after_obs":
                findings.extend(self._rule_forbid_phrase_after_obs(rule, trace, pairs))
            elif rtype == "duplicate_mutating_call":
                findings.extend(self._rule_duplicate_mutating_call(rule, pairs))
            elif rtype == "entity_grounding":
                findings.extend(self._rule_entity_grounding(rule, trace, pairs))
            elif rtype == "ignored_user_entity":
                findings.extend(self._rule_ignored_user_entity(rule, trace, pairs))
            elif rtype == "tool_misroute_to_search":
                findings.extend(self._rule_tool_misroute_to_search(rule, trace, pairs))

        return findings

    def _rule_require_prior_tool(
        self, rule: dict[str, Any], pairs: list[tuple[ToolCall, Optional[ToolResult]]]
    ) -> list[Finding]:
        target_tool = rule["tool"]
        required_tools = set(rule["required_tools"])
        match_key = rule.get("match_key")
        require_success = bool(rule.get("require_success", True))
        seen: list[tuple[ToolCall, Optional[ToolResult]]] = []
        out: list[Finding] = []

        for tc, tr in pairs:
            if tc.name == target_tool:
                target_val = _extract_value(tc.arguments, match_key) if match_key else None
                satisfied = False
                for ptc, ptr in seen:
                    if ptc.name not in required_tools:
                        continue
                    if require_success and (ptr is None or ptr.is_error):
                        continue
                    if match_key and target_val is not None:
                        pval = _extract_value(ptc.arguments, match_key)
                        # Also allow prior list tools whose result contains matching entity
                        obs_match = False
                        if ptr and isinstance(ptr.parsed_content, dict):
                            if ptr.parsed_content.get(match_key) == target_val:
                                obs_match = True
                            for lst_val in ptr.parsed_content.values():
                                if isinstance(lst_val, list):
                                    for item in lst_val:
                                        if isinstance(item, dict) and item.get(match_key) == target_val:
                                            obs_match = True
                        if pval != target_val and not obs_match:
                            continue
                    satisfied = True
                    break
                if not satisfied:
                    out.append(
                        Finding(
                            code=rule["code"],
                            category=rule.get("category", "policy"),
                            severity=rule.get("severity", "high"),
                            message=rule.get(
                                "message",
                                f"Tool '{target_tool}' called without required prior tool {sorted(required_tools)}.",
                            ),
                            step_indices=[tc.turn_index],
                            tool_name=target_tool,
                            evidence={
                                "arguments": tc.arguments,
                                "required_tools": sorted(required_tools),
                                "match_key": match_key,
                            },
                            detector=self.name,
                        )
                    )
            seen.append((tc, tr))
        return out

    def _rule_forbid_tool_after_obs(
        self, rule: dict[str, Any], pairs: list[tuple[ToolCall, Optional[ToolResult]]]
    ) -> list[Finding]:
        trigger_tool = rule["trigger_tool"]
        forbidden_tool = rule["forbidden_tool"]
        condition = rule["condition"]
        match_key = rule.get("match_key")
        triggered_keys: dict[Any, tuple[int, Any]] = {}
        out: list[Finding] = []

        for tc, tr in pairs:
            if tc.name == trigger_tool and tr is not None and not tr.is_error:
                if _eval_condition(tr.parsed_content, condition):
                    k = _extract_value(tc.arguments, match_key) if match_key else "__any__"
                    triggered_keys[k] = (tc.turn_index, tr.parsed_content)
            elif tc.name == forbidden_tool:
                k = _extract_value(tc.arguments, match_key) if match_key else "__any__"
                hit = triggered_keys.get(k) or triggered_keys.get("__any__")
                if hit is not None:
                    trig_step, trig_obs = hit
                    succeeded = bool(tr is not None and not tr.is_error)
                    out.append(
                        Finding(
                            code=rule["code"],
                            category=rule.get("category", "policy"),
                            severity=rule.get("severity", "critical"),
                            message=rule.get(
                                "message",
                                f"Agent called '{forbidden_tool}' after '{trigger_tool}' returned disqualifying observation.",
                            ),
                            step_indices=[trig_step, tc.turn_index],
                            tool_name=forbidden_tool,
                            evidence={
                                "arguments": tc.arguments,
                                "trigger_observation": trig_obs,
                                "forbidden_call_succeeded": succeeded,
                            },
                            detector=self.name,
                        )
                    )
        return out

    def _rule_amount_consistency(
        self, rule: dict[str, Any], pairs: list[tuple[ToolCall, Optional[ToolResult]]]
    ) -> list[Finding]:
        target_tool = rule["target_tool"]
        target_field = rule["target_field"]
        match_key = rule.get("match_key")
        ref_sources = rule.get("reference_sources") or []  # list of {tool, field}
        items_field = rule.get("items_field", "items")
        item_amount_field = rule.get("item_amount_field", "amount_cents")
        ref_values: dict[Any, tuple[int, str, Any]] = {}
        item_amounts: dict[Any, set[int]] = defaultdict(set)
        out: list[Finding] = []

        for tc, tr in pairs:
            if tr is not None and not tr.is_error and isinstance(tr.parsed_content, dict):
                k = _extract_value(tc.arguments, match_key) if match_key else "__any__"
                # Collect valid partial-refund item amounts (single items + eligible subset sums)
                raw_items = tr.parsed_content.get(items_field)
                if isinstance(raw_items, list):
                    vals = [
                        it[item_amount_field]
                        for it in raw_items
                        if isinstance(it, dict)
                        and isinstance(it.get(item_amount_field), int)
                        and not isinstance(it.get(item_amount_field), bool)
                    ]
                    if vals and len(vals) <= 10:
                        for mask in range(1, 1 << len(vals)):
                            s = sum(vals[i] for i in range(len(vals)) if mask & (1 << i))
                            item_amounts[k].add(s)

                for src in ref_sources:
                    if tc.name == src["tool"] and src["field"] in tr.parsed_content:
                        val = tr.parsed_content[src["field"]]
                        if isinstance(val, (int, float)) and not isinstance(val, bool):
                            ref_values[k] = (tc.turn_index, f"{src['tool']}.{src['field']}", val)

            if tc.name == target_tool and isinstance(tc.arguments, dict) and target_field in tc.arguments:
                amt = tc.arguments[target_field]
                if not isinstance(amt, (int, float)) or isinstance(amt, bool):
                    continue
                k = _extract_value(tc.arguments, match_key) if match_key else "__any__"
                ref = ref_values.get(k) or ref_values.get("__any__")
                if ref is None:
                    continue
                ref_step, ref_label, ref_amt = ref
                if ref_amt == 0 or amt == ref_amt:
                    continue
                if amt in item_amounts.get(k, set()):
                    # Exact match to one or more line items (valid partial refund)
                    continue

                if amt * 100 == ref_amt:
                    out.append(
                        Finding(
                            code=rule.get("unit_mismatch_code", f"{rule['code']}_unit_mismatch"),
                            category=rule.get("category", "policy"),
                            severity="critical",
                            message=(
                                f"Possible dollars-vs-cents error on '{target_tool}.{target_field}': "
                                f"sent {amt} vs expected {ref_amt} ({ref_label})."
                            ),
                            step_indices=[ref_step, tc.turn_index],
                            tool_name=target_tool,
                            evidence={"sent": amt, "reference": ref_amt, "reference_source": ref_label, "key": k},
                            detector=self.name,
                        )
                    )
                elif amt > ref_amt:
                    out.append(
                        Finding(
                            code=rule.get("over_amount_code", f"{rule['code']}_over_reference"),
                            category=rule.get("category", "policy"),
                            severity="critical",
                            message=(
                                f"Over-amount on '{target_tool}.{target_field}': "
                                f"sent {amt} > {ref_amt} ({ref_label})."
                            ),
                            step_indices=[ref_step, tc.turn_index],
                            tool_name=target_tool,
                            evidence={"sent": amt, "reference": ref_amt, "reference_source": ref_label, "key": k},
                            detector=self.name,
                        )
                    )
                elif amt < ref_amt:
                    out.append(
                        Finding(
                            code=rule.get("under_amount_code", f"{rule['code']}_under_reference"),
                            category=rule.get("category", "policy"),
                            severity="high",
                            message=(
                                f"Under-amount on '{target_tool}.{target_field}': "
                                f"sent {amt} < {ref_amt} ({ref_label})."
                            ),
                            step_indices=[ref_step, tc.turn_index],
                            tool_name=target_tool,
                            evidence={"sent": amt, "reference": ref_amt, "reference_source": ref_label, "key": k},
                            detector=self.name,
                        )
                    )
        return out

    def _rule_claim_requires_tool_success(
        self,
        rule: dict[str, Any],
        trace: CanonicalTrace,
        pairs: list[tuple[ToolCall, Optional[ToolResult]]],
    ) -> list[Finding]:
        req_tool = rule["required_tool"]
        claim_patterns = rule["claim_patterns"]
        negation_patterns = rule.get("negation_patterns") or []
        result_cond = rule.get("result_condition")

        # Determine earliest turn index where required_tool succeeded
        success_steps: list[int] = []
        failed_steps: list[int] = []
        for tc, tr in pairs:
            if tc.name != req_tool:
                continue
            if tr is not None and not tr.is_error:
                if result_cond is None or _eval_condition(tr.parsed_content, result_cond):
                    success_steps.append(tc.turn_index)
                else:
                    failed_steps.append(tc.turn_index)
            else:
                failed_steps.append(tc.turn_index)

        earliest_ok = min(success_steps) if success_steps else None
        out: list[Finding] = []
        for turn in trace.turns:
            if turn.role != "agent" or not turn.content.strip():
                continue
            # Check sentence-by-sentence so a negation in an unrelated sentence doesn't mask a false claim
            sentences = re.split(r"(?<=[.!?])\s+|\n+", turn.content)
            for sent in sentences:
                matched = _matches_any(sent, claim_patterns)
                if not matched:
                    continue
                if negation_patterns and _matches_any(sent, negation_patterns):
                    continue
                if earliest_ok is None or turn.index < earliest_ok:
                    out.append(
                        Finding(
                            code=rule["code"],
                            category=rule.get("category", "grounding"),
                            severity=rule.get("severity", "critical"),
                            message=rule.get(
                                "message",
                                f"Agent claimed completion ('{matched}') without a prior successful '{req_tool}' call.",
                            ),
                            step_indices=[turn.index],
                            tool_name=req_tool,
                            evidence={
                                "matched_phrase": matched,
                                "sentence_excerpt": sent.strip()[:180],
                                "prior_tool_failures": [s for s in failed_steps if s <= turn.index],
                                "tool_ever_succeeded": earliest_ok is not None,
                            },
                            detector=self.name,
                        )
                    )
                    break
        return out

    def _rule_forbid_phrase_after_obs(
        self,
        rule: dict[str, Any],
        trace: CanonicalTrace,
        pairs: list[tuple[ToolCall, Optional[ToolResult]]],
    ) -> list[Finding]:
        trigger_tool = rule["trigger_tool"]
        condition = rule["condition"]
        phrase_patterns = rule["phrase_patterns"]
        negation_patterns = rule.get("negation_patterns") or []

        trigger_step: Optional[int] = None
        for tc, tr in pairs:
            if tc.name == trigger_tool and tr is not None and not tr.is_error:
                if _eval_condition(tr.parsed_content, condition):
                    trigger_step = tc.turn_index
                    break

        if trigger_step is None:
            return []

        out: list[Finding] = []
        for turn in trace.turns:
            if turn.role != "agent" or turn.index < trigger_step or not turn.content.strip():
                continue
            sentences = re.split(r"(?<=[.!?])\s+|\n+", turn.content)
            for sent in sentences:
                matched = _matches_any(sent, phrase_patterns)
                if matched and not (negation_patterns and _matches_any(sent, negation_patterns)):
                    out.append(
                        Finding(
                            code=rule["code"],
                            category=rule.get("category", "policy"),
                            severity=rule.get("severity", "high"),
                            message=rule.get(
                                "message",
                                f"Agent used forbidden phrase ('{matched}') after '{trigger_tool}' condition matched.",
                            ),
                            step_indices=[trigger_step, turn.index],
                            tool_name=trigger_tool,
                            evidence={"matched_phrase": matched, "sentence_excerpt": sent.strip()[:180]},
                            detector=self.name,
                        )
                    )
                    break
        return out

    def _rule_duplicate_mutating_call(
        self, rule: dict[str, Any], pairs: list[tuple[ToolCall, Optional[ToolResult]]]
    ) -> list[Finding]:
        target_tool = rule["tool"]
        key_field = rule.get("key_field")
        seen_ok: dict[Any, list[int]] = defaultdict(list)
        out: list[Finding] = []
        for tc, tr in pairs:
            if tc.name == target_tool and tr is not None and not tr.is_error:
                k = _extract_value(tc.arguments, key_field) if key_field else "__any__"
                seen_ok[k].append(tc.turn_index)
        for k, steps in seen_ok.items():
            if len(steps) > 1:
                out.append(
                    Finding(
                        code=rule["code"],
                        category=rule.get("category", "policy"),
                        severity=rule.get("severity", "critical"),
                        message=f"Mutating tool '{target_tool}' succeeded {len(steps)} times for key {k!r}.",
                        step_indices=steps,
                        tool_name=target_tool,
                        evidence={"key": k, "success_count": len(steps)},
                        detector=self.name,
                    )
                )
        return out

    def _rule_entity_grounding(
        self,
        rule: dict[str, Any],
        trace: CanonicalTrace,
        pairs: list[tuple[ToolCall, Optional[ToolResult]]],
    ) -> list[Finding]:
        tools = set(rule["tools"])
        arg_field = rule["arg_field"]
        entity_re = re.compile(rule["pattern"])
        known_entities: set[str] = set()
        out: list[Finding] = []

        # Walk chronologically by turn
        pair_by_turn: dict[int, list[tuple[ToolCall, Optional[ToolResult]]]] = defaultdict(list)
        for tc, tr in pairs:
            pair_by_turn[tc.turn_index].append((tc, tr))

        for turn in trace.turns:
            if turn.role == "user":
                known_entities.update(entity_re.findall(turn.content))
            for tc, tr in pair_by_turn.get(turn.index, []):
                if tc.name in tools and isinstance(tc.arguments, dict) and arg_field in tc.arguments:
                    val = tc.arguments[arg_field]
                    if isinstance(val, str) and entity_re.fullmatch(val) and val not in known_entities:
                        out.append(
                            Finding(
                                code=rule["code"],
                                category=rule.get("category", "grounding"),
                                severity=rule.get("severity", "high"),
                                message=(
                                    f"Tool '{tc.name}' invoked with ungrounded {arg_field}={val!r} "
                                    f"(not seen in user messages or prior tool outputs)."
                                ),
                                step_indices=[tc.turn_index],
                                tool_name=tc.name,
                                evidence={"arg_value": val, "known_entities": sorted(known_entities)},
                                detector=self.name,
                            )
                        )
                if tr is not None:
                    raw = tr.raw_content if isinstance(tr.raw_content, str) else json.dumps(tr.raw_content)
                    known_entities.update(entity_re.findall(raw))
        return out

    def _rule_ignored_user_entity(
        self,
        rule: dict[str, Any],
        trace: CanonicalTrace,
        pairs: list[tuple[ToolCall, Optional[ToolResult]]],
    ) -> list[Finding]:
        entity_patterns = rule["entity_patterns"]
        consuming_tools = set(rule["consuming_tools"])
        arg_fields = set(rule.get("arg_fields") or [])
        user_entities: list[tuple[int, str]] = []

        for turn in trace.turns:
            if turn.role != "user":
                continue
            for pat in entity_patterns:
                for m in re.finditer(pat, turn.content, re.IGNORECASE):
                    user_entities.append((turn.index, m.group(0)))

        if not user_entities:
            return []

        # Check if ANY consuming tool was invoked with any argument containing a provided entity (or digits)
        used_values: list[str] = []
        for tc, _ in pairs:
            if tc.name in consuming_tools and isinstance(tc.arguments, dict):
                for k, v in tc.arguments.items():
                    if not arg_fields or k in arg_fields:
                        if isinstance(v, str):
                            used_values.append(v.lower())

        def _entity_used(ent: str) -> bool:
            e = ent.lower().lstrip("#")
            digits = re.sub(r"\D", "", e)
            for uv in used_values:
                if e in uv or (len(digits) >= 4 and digits in uv):
                    return True
            return False

        # If NONE of the user-provided entities were ever passed to a consuming tool, flag!
        if not any(_entity_used(ent) for _, ent in user_entities):
            # Only flag if outcome wasn't resolved (or zero consuming tools called)
            if trace.outcome != "resolved":
                first_step = user_entities[0][0]
                return [
                    Finding(
                        code=rule["code"],
                        category=rule.get("category", "grounding"),
                        severity=rule.get("severity", "high"),
                        message=rule.get(
                            "message",
                            f"User provided entity {user_entities[0][1]!r}, but agent never passed it to {sorted(consuming_tools)}.",
                        ),
                        step_indices=[first_step],
                        evidence={
                            "user_entities": sorted({e for _, e in user_entities}),
                            "used_tool_args": used_values,
                            "outcome": trace.outcome,
                        },
                        detector=self.name,
                    )
                ]
        return []

    def _rule_tool_misroute_to_search(
        self,
        rule: dict[str, Any],
        trace: CanonicalTrace,
        pairs: list[tuple[ToolCall, Optional[ToolResult]]],
    ) -> list[Finding]:
        search_tools = set(rule["search_tools"])
        action_tools = set(rule["action_tools"])
        entity_patterns = rule["entity_patterns"]

        called = [tc.name for tc, _ in pairs]
        if not called:
            return []
        if not (set(called) <= search_tools):
            return []
        if set(called) & action_tools:
            return []

        user_text = "\n".join(t.content for t in trace.turns if t.role == "user")
        matched_ent = _matches_any(user_text, entity_patterns)
        if matched_ent and trace.outcome != "resolved":
            steps = [tc.turn_index for tc, _ in pairs if tc.name in search_tools]
            return [
                Finding(
                    code=rule["code"],
                    category=rule.get("category", "routing"),
                    severity=rule.get("severity", "high"),
                    message=rule.get(
                        "message",
                        f"User provided specific entity {matched_ent!r}, but agent only called FAQ/search tool(s) {sorted(set(called))} instead of action tools.",
                    ),
                    step_indices=steps,
                    tool_name=called[0],
                    evidence={
                        "user_entity": matched_ent,
                        "search_calls": len(called),
                        "tools_called": called,
                    },
                    detector=self.name,
                )
            ]
        return []
