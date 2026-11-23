"""Universal format- and domain-agnostic trace detectors + dynamic plugin loader."""

from __future__ import annotations

import importlib.util
import json
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .model import CanonicalTrace, Finding
from .tool_schema import validate_tool_call

APOLOGY_RE = re.compile(
    r"\b(sorry|apologize|apologies|apologise|sincerely sorry|regret the inconvenience|for the inconvenience)\b",
    re.IGNORECASE,
)

# Generic structured identifier pattern (e.g. REF-1234, RF-999, TRK-882, NL-4412, ESC-102, 1Z999AA10123456784)
STRUCTURED_ID_RE = re.compile(
    r"\b(?:(?:REF|RF|RFD|ESC|TRK|TRACK|NL|ORD|TKT|CASE)-[A-Z0-9]{2,}|1Z[A-Z0-9]{10,})\b"
)

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _canonical_args(args: Any) -> str:
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(args)


def _jaccard(a: str, b: str) -> float:
    ta = set(TOKEN_RE.findall(a.lower()))
    tb = set(TOKEN_RE.findall(b.lower()))
    if len(ta) < 6 or len(tb) < 6:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class TraceDetector(ABC):
    """Base class for pluggable trace detectors."""

    name: str = "base_detector"

    @abstractmethod
    def detect(self, trace: CanonicalTrace) -> list[Finding]:
        """Inspect a CanonicalTrace and emit zero or more structured Findings."""


class ToolSchemaDetector(TraceDetector):
    """Validates every tool call against inline or external JSON Schema tool specs."""

    name = "tool_schema"

    def detect(self, trace: CanonicalTrace) -> list[Finding]:
        findings: list[Finding] = []
        if not trace.tool_specs:
            return findings

        for tc, tr in trace.tool_call_pairs():
            if tc.parse_error:
                findings.append(
                    Finding(
                        code="tool_schema.malformed_arguments_json",
                        category="tool_contract",
                        severity="high",
                        message=f"Tool '{tc.name}' arguments failed JSON parsing: {tc.parse_error}",
                        step_indices=[tc.turn_index],
                        tool_name=tc.name,
                        evidence={"raw_arguments": str(tc.raw_arguments)[:160]},
                        detector=self.name,
                    )
                )
                continue

            violations = validate_tool_call(tc.name, tc.arguments, trace.tool_specs)
            for v in violations:
                sev = "high" if v.kind in {"unknown_tool", "missing_required_arg", "invalid_arg_type", "invalid_enum_value"} else "medium"
                findings.append(
                    Finding(
                        code=f"tool_schema.{v.kind}",
                        category="tool_contract",
                        severity=sev,
                        message=v.message,
                        step_indices=[tc.turn_index],
                        tool_name=tc.name,
                        evidence={
                            "field": v.field,
                            "expected": v.expected,
                            "actual": v.actual,
                            "arguments": tc.arguments,
                            "tool_returned_error": bool(tr and tr.is_error),
                            "status_code": tr.status_code if tr else None,
                        },
                        detector=self.name,
                    )
                )
        return findings


class ToolErrorLoopDetector(TraceDetector):
    """Detects tool errors, identical failing retries, repeated failures, and unrecovered errors."""

    name = "tool_error_loop"

    def detect(self, trace: CanonicalTrace) -> list[Finding]:
        findings: list[Finding] = []
        pairs = trace.tool_call_pairs()

        failed_signatures: dict[tuple[str, str], list[int]] = defaultdict(list)
        tool_error_steps: dict[str, list[int]] = defaultdict(list)
        tool_success_after: dict[str, int] = {}

        for idx, (tc, tr) in enumerate(pairs):
            sig = (tc.name, _canonical_args(tc.arguments))
            if tr is None:
                findings.append(
                    Finding(
                        code="tool_error.missing_observation",
                        category="error_handling",
                        severity="medium",
                        message=f"Tool call '{tc.name}' (id={tc.call_id}) has no matching observation result.",
                        step_indices=[tc.turn_index],
                        tool_name=tc.name,
                        evidence={"call_id": tc.call_id, "arguments": tc.arguments},
                        detector=self.name,
                    )
                )
                continue

            if tr.is_error:
                # Check if this exact failing payload was already tried and failed before
                if sig in failed_signatures:
                    findings.append(
                        Finding(
                            code="tool_error.identical_retry_after_failure",
                            category="error_handling",
                            severity="high",
                            message=(
                                f"Agent retried identical failing payload for '{tc.name}' "
                                f"(previously failed at step {failed_signatures[sig][-1]})."
                            ),
                            step_indices=[failed_signatures[sig][-1], tc.turn_index],
                            tool_name=tc.name,
                            evidence={
                                "arguments": tc.arguments,
                                "error": tr.error_message,
                                "status_code": tr.status_code,
                                "attempt_count": len(failed_signatures[sig]) + 1,
                            },
                            detector=self.name,
                        )
                    )
                failed_signatures[sig].append(tc.turn_index)
                tool_error_steps[tc.name].append(tc.turn_index)

                findings.append(
                    Finding(
                        code="tool_error.call_failed",
                        category="error_handling",
                        severity="medium",
                        message=f"Tool '{tc.name}' returned error: {tr.error_message or 'unknown error'}",
                        step_indices=[tc.turn_index],
                        tool_name=tc.name,
                        evidence={
                            "arguments": tc.arguments,
                            "status_code": tr.status_code,
                            "error": tr.error_message,
                        },
                        detector=self.name,
                    )
                )
            else:
                tool_success_after[tc.name] = tc.turn_index

        for tname, err_steps in tool_error_steps.items():
            if len(err_steps) >= 2:
                findings.append(
                    Finding(
                        code="tool_error.repeated_failures",
                        category="error_handling",
                        severity="high",
                        message=f"Tool '{tname}' failed {len(err_steps)} times in session.",
                        step_indices=err_steps,
                        tool_name=tname,
                        evidence={"failure_count": len(err_steps)},
                        detector=self.name,
                    )
                )
            last_err = err_steps[-1]
            last_ok = tool_success_after.get(tname, -1)
            if last_ok < last_err:
                findings.append(
                    Finding(
                        code="tool_error.unrecovered_error",
                        category="error_handling",
                        severity="high",
                        message=f"Tool '{tname}' failed at step {last_err} and never succeeded afterward.",
                        step_indices=[last_err],
                        tool_name=tname,
                        evidence={"last_error_step": last_err, "outcome": trace.outcome},
                        detector=self.name,
                    )
                )

        return findings


class ConversationQualityDetector(TraceDetector):
    """Detects apology loops, repetitive agent messages, stalling, and missing escalations."""

    name = "conversation_quality"

    def __init__(self, excessive_turn_threshold: int = 12, escalation_tools: Optional[set[str]] = None):
        self.excessive_turn_threshold = excessive_turn_threshold
        self.escalation_tools = escalation_tools or {"escalate_ticket", "escalate", "handoff", "transfer_to_human"}

    def detect(self, trace: CanonicalTrace) -> list[Finding]:
        findings: list[Finding] = []
        agent_msg_turns = [t for t in trace.turns if t.role == "agent" and t.content.strip()]

        apology_steps = [t.index for t in agent_msg_turns if APOLOGY_RE.search(t.content)]
        # Check whether the session ever resolved cleanly or had repeated apologies without progress
        if len(apology_steps) >= 3:
            findings.append(
                Finding(
                    code="conversation.apology_loop",
                    category="conversation",
                    severity="high",
                    message=f"Agent entered an apology loop ({len(apology_steps)} apologetic turns).",
                    step_indices=apology_steps,
                    evidence={
                        "apology_turn_count": len(apology_steps),
                        "total_agent_msg_turns": len(agent_msg_turns),
                        "outcome": trace.outcome,
                    },
                    detector=self.name,
                )
            )
        elif len(apology_steps) == 2 and trace.outcome in {"failed", "escalated", None}:
            findings.append(
                Finding(
                    code="conversation.repeated_apology",
                    category="conversation",
                    severity="medium",
                    message=f"Agent apologized repeatedly ({len(apology_steps)} turns) in a non-resolved session.",
                    step_indices=apology_steps,
                    evidence={"apology_turn_count": len(apology_steps), "outcome": trace.outcome},
                    detector=self.name,
                )
            )

        # Consecutive repetitive agent responses
        rep_pairs: list[tuple[int, int, float]] = []
        for prev, curr in zip(agent_msg_turns, agent_msg_turns[1:]):
            sim = _jaccard(prev.content, curr.content)
            if sim >= 0.65:
                rep_pairs.append((prev.index, curr.index, round(sim, 3)))
        if rep_pairs:
            steps = sorted({s for a, b, _ in rep_pairs for s in (a, b)})
            findings.append(
                Finding(
                    code="conversation.repetitive_responses",
                    category="conversation",
                    severity="medium",
                    message=f"Agent repeated highly similar responses across consecutive turns ({len(rep_pairs)} pair(s)).",
                    step_indices=steps,
                    evidence={"pairs": [{"from": a, "to": b, "jaccard": sim} for a, b, sim in rep_pairs]},
                    detector=self.name,
                )
            )

        if len(trace.turns) >= self.excessive_turn_threshold:
            findings.append(
                Finding(
                    code="conversation.excessive_turns",
                    category="conversation",
                    severity="low",
                    message=f"Session has {len(trace.turns)} turns (threshold={self.excessive_turn_threshold}).",
                    step_indices=[trace.turns[-1].index],
                    evidence={"turn_count": len(trace.turns), "outcome": trace.outcome},
                    detector=self.name,
                )
            )

        called_tools = {tc.name for tc in trace.all_tool_calls()}
        escalated_via_tool = bool(called_tools & self.escalation_tools)
        if trace.outcome == "failed" and not escalated_via_tool:
            findings.append(
                Finding(
                    code="outcome.failed_without_escalation",
                    category="outcome",
                    severity="high",
                    message="Session ended with outcome='failed' and agent never invoked an escalation/handoff tool.",
                    step_indices=[trace.turns[-1].index] if trace.turns else [],
                    evidence={"outcome": trace.outcome, "tools_called": sorted(called_tools)},
                    detector=self.name,
                )
            )

        return findings


class GroundingDetector(TraceDetector):
    """Detects fabricated structured IDs quoted by the agent that never appeared in inputs or tool results."""

    name = "grounding"

    def detect(self, trace: CanonicalTrace) -> list[Finding]:
        findings: list[Finding] = []
        known_ids: set[str] = set()

        # System prompt example IDs (e.g. "e.g. NL-4412") should NOT count as real customer data,
        # unless the user or a tool returns them.
        for turn in trace.turns:
            if turn.role == "user":
                known_ids.update(STRUCTURED_ID_RE.findall(turn.content))
            for tc in turn.tool_calls:
                # IDs already sent to tools are audited separately by entity_grounding;
                # if a tool accepted them, avoid double-flagging an agent confession later.
                raw_args = tc.raw_arguments if isinstance(tc.raw_arguments, str) else json.dumps(tc.arguments)
                if raw_args:
                    known_ids.update(STRUCTURED_ID_RE.findall(raw_args))
            for tr in turn.tool_results:
                raw_str = tr.raw_content if isinstance(tr.raw_content, str) else json.dumps(tr.raw_content)
                known_ids.update(STRUCTURED_ID_RE.findall(raw_str))
            if turn.role == "agent" and turn.content:
                cited_ids = set(STRUCTURED_ID_RE.findall(turn.content))
                fabricated = sorted(cited_ids - known_ids)
                if fabricated:
                    findings.append(
                        Finding(
                            code="grounding.fabricated_identifier",
                            category="grounding",
                            severity="critical",
                            message=f"Agent cited structured ID(s) {fabricated} never returned by tools or provided by user.",
                            step_indices=[turn.index],
                            evidence={"fabricated_ids": fabricated, "known_ids": sorted(known_ids)},
                            detector=self.name,
                        )
                    )
        return findings


def default_detectors() -> list[TraceDetector]:
    """Return the standard suite of universal format-agnostic detectors."""
    return [
        ToolSchemaDetector(),
        ToolErrorLoopDetector(),
        ConversationQualityDetector(),
        GroundingDetector(),
    ]


def load_plugin_detectors(plugin_path: str | Path) -> list[TraceDetector]:
    """Dynamically load custom TraceDetector subclasses or `get_detectors()` from a Python file."""
    p = Path(plugin_path)
    spec = importlib.util.spec_from_file_location(f"trace_review_plugin_{p.stem}", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load plugin module from {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if hasattr(mod, "get_detectors") and callable(mod.get_detectors):
        return list(mod.get_detectors())

    detectors: list[TraceDetector] = []
    for attr in vars(mod).values():
        if isinstance(attr, type) and issubclass(attr, TraceDetector) and attr is not TraceDetector:
            detectors.append(attr())
    return detectors
