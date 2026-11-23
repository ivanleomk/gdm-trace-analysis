"""Canonical Intermediate Representation (IR) for multi-format agent traces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ToolSpec:
    """Normalized JSON-Schema-backed specification of a callable tool."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    source: str = "inline"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCall:
    """Normalized invocation of a tool by an agent."""

    call_id: str
    name: str
    arguments: Any
    turn_index: int
    raw_arguments: Any = None
    parse_error: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResult:
    """Normalized observation/result returned for a tool invocation."""

    call_id: str
    tool_name: Optional[str]
    raw_content: Any
    parsed_content: Any
    turn_index: int
    is_error: bool = False
    error_message: Optional[str] = None
    status_code: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalTurn:
    """Normalized single step/message/event in an agent trajectory."""

    index: int
    role: str  # system | user | agent | tool | event
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    step_id: Optional[Any] = None
    timestamp: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "role": self.role,
            "content": self.content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_results": [tr.to_dict() for tr in self.tool_results],
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "extra": self.extra,
        }


@dataclass
class CanonicalTrace:
    """Format-independent representation of a complete agent session/trajectory."""

    trace_id: str
    source_format: str
    turns: list[CanonicalTurn] = field(default_factory=list)
    schema_version: Optional[str] = None
    agent_name: Optional[str] = None
    model_name: Optional[str] = None
    agent_version: Optional[str] = None
    system_prompt: Optional[str] = None
    tool_specs: dict[str, ToolSpec] = field(default_factory=dict)
    outcome: Optional[str] = None
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def all_tool_calls(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for turn in self.turns:
            calls.extend(turn.tool_calls)
        return calls

    def all_tool_results(self) -> list[ToolResult]:
        results: list[ToolResult] = []
        for turn in self.turns:
            results.extend(turn.tool_results)
        return results

    def tool_call_pairs(self) -> list[tuple[ToolCall, Optional[ToolResult]]]:
        """Pair every ToolCall with its matching ToolResult by call_id."""
        by_id: dict[str, ToolResult] = {}
        for tr in self.all_tool_results():
            if tr.call_id:
                by_id[tr.call_id] = tr
        return [(tc, by_id.get(tc.call_id)) for tc in self.all_tool_calls()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "source_format": self.source_format,
            "schema_version": self.schema_version,
            "agent_name": self.agent_name,
            "model_name": self.model_name,
            "agent_version": self.agent_version,
            "system_prompt": self.system_prompt,
            "tool_specs": {k: v.to_dict() for k, v in self.tool_specs.items()},
            "turns": [t.to_dict() for t in self.turns],
            "outcome": self.outcome,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "extra": self.extra,
        }


@dataclass
class Finding:
    """A structured diagnostic finding emitted by a detector or policy rule."""

    code: str
    category: str
    severity: str  # critical | high | medium | low | info
    message: str
    step_indices: list[int] = field(default_factory=list)
    tool_name: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    detector: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
