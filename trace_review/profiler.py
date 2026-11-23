"""Single-pass streaming schema & corpus profiler for unknown/novel trace formats."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from .model import CanonicalTrace


@dataclass
class CorpusProfile:
    """Compact structural summary of a trace corpus without reading full transcripts."""

    total_traces: int = 0
    formats: dict[str, int] = field(default_factory=dict)
    schema_versions: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    outcomes: dict[str, int] = field(default_factory=dict)
    unique_system_prompts: int = 0
    turn_stats: dict[str, float] = field(default_factory=dict)
    role_counts: dict[str, int] = field(default_factory=dict)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    tool_error_counts: dict[str, int] = field(default_factory=dict)
    tool_error_rates: dict[str, float] = field(default_factory=dict)
    tool_error_signatures: dict[str, int] = field(default_factory=dict)
    undefined_tools_called: list[str] = field(default_factory=list)
    unused_defined_tools: list[str] = field(default_factory=list)
    extra_key_coverage: dict[str, int] = field(default_factory=dict)
    observation_shapes_by_tool: dict[str, list[list[str]]] = field(default_factory=dict)
    tool_arg_shapes: dict[str, list[list[str]]] = field(default_factory=dict)
    schema_drift_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            "# Trace Corpus Profile",
            "",
            f"- **Total traces**: {self.total_traces}",
            f"- **Formats detected**: {self.formats}",
            f"- **Schema versions**: {self.schema_versions or {'(none)': self.total_traces}}",
            f"- **Models**: {self.models or {'(unspecified)': self.total_traces}}",
            f"- **Unique system prompts**: {self.unique_system_prompts}",
            f"- **Turns (min / median / avg / max)**: "
            f"{self.turn_stats.get('min', 0)} / {self.turn_stats.get('median', 0)} / "
            f"{self.turn_stats.get('avg', 0)} / {self.turn_stats.get('max', 0)}",
            "",
            "## Outcomes",
            "",
            "| Outcome | Sessions | Share |",
            "|---|---:|---:|",
        ]
        for k, v in sorted(self.outcomes.items(), key=lambda kv: (-kv[1], kv[0])):
            pct = (100.0 * v / self.total_traces) if self.total_traces else 0.0
            lines.append(f"| `{k}` | {v} | {pct:.1f}% |")

        lines.extend([
            "",
            "## Tool Usage & Error Rates",
            "",
            "| Tool | Calls | Errors | Error Rate | Arg Key Shapes |",
            "|---|---:|---:|---:|---|",
        ])
        for tool, count in sorted(self.tool_call_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            errs = self.tool_error_counts.get(tool, 0)
            rate = self.tool_error_rates.get(tool, 0.0) * 100.0
            shapes = ", ".join("{" + ",".join(s) + "}" for s in self.tool_arg_shapes.get(tool, [])[:3])
            lines.append(f"| `{tool}` | {count} | {errs} | {rate:.1f}% | `{shapes}` |")

        if self.tool_error_signatures:
            lines.extend(["", "## Top Tool Error Signatures", ""])
            for sig, cnt in sorted(self.tool_error_signatures.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
                lines.append(f"- **{cnt}x** `{sig}`")

        if self.observation_shapes_by_tool:
            lines.extend(["", "## Observation Payload Shapes (Keys Only)", ""])
            for tool, shapes in sorted(self.observation_shapes_by_tool.items()):
                formatted = "; ".join("{" + ", ".join(s) + "}" for s in shapes[:5])
                lines.append(f"- **`{tool}`**: `{formatted}`")

        if self.schema_drift_warnings:
            lines.extend(["", "## Novelty & Schema Drift Warnings", ""])
            for w in self.schema_drift_warnings:
                lines.append(f"- {w}")

        return "\n".join(lines) + "\n"


def profile_traces(traces: Iterable[CanonicalTrace]) -> CorpusProfile:
    """Compute a streaming corpus profile in O(1) memory per trace."""
    total = 0
    formats: Counter[str] = Counter()
    schema_versions: Counter[str] = Counter()
    models: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    tool_calls: Counter[str] = Counter()
    tool_errors: Counter[str] = Counter()
    err_sigs: Counter[str] = Counter()
    extra_keys: Counter[str] = Counter()
    defined_tools: set[str] = set()
    sys_prompt_hashes: set[int] = set()
    turn_lengths: list[int] = []
    obs_shapes: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    arg_shapes: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    drift_warnings: list[str] = []

    for trace in traces:
        total += 1
        formats[trace.source_format] += 1
        if trace.schema_version:
            schema_versions[trace.schema_version] += 1
        if trace.model_name:
            models[trace.model_name] += 1
        outcomes[trace.outcome or "(none)"] += 1
        if trace.system_prompt is not None:
            sys_prompt_hashes.add(hash(trace.system_prompt))
        defined_tools.update(trace.tool_specs.keys())
        extra_keys.update(trace.extra.keys())
        turn_lengths.append(len(trace.turns))

        for turn in trace.turns:
            roles[turn.role] += 1

        for tc, tr in trace.tool_call_pairs():
            tool_calls[tc.name] += 1
            if isinstance(tc.arguments, dict):
                arg_shapes[tc.name].add(tuple(sorted(tc.arguments.keys())))
            else:
                arg_shapes[tc.name].add((f"<{type(tc.arguments).__name__}>",))

            if tr is not None:
                if isinstance(tr.parsed_content, dict):
                    obs_shapes[tc.name].add(tuple(sorted(tr.parsed_content.keys())))
                else:
                    obs_shapes[tc.name].add((f"<{type(tr.parsed_content).__name__}>",))
                if tr.is_error:
                    tool_errors[tc.name] += 1
                    code_part = f"HTTP {tr.status_code}" if tr.status_code else "ERR"
                    msg_part = (tr.error_message or "unknown")[:80]
                    err_sigs[f"{tc.name} | {code_part} | {msg_part}"] += 1

    turn_stats: dict[str, float] = {}
    if turn_lengths:
        s = sorted(turn_lengths)
        mid = len(s) // 2
        med = s[mid] if len(s) % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0
        turn_stats = {
            "min": float(s[0]),
            "median": float(med),
            "avg": round(sum(s) / len(s), 2),
            "max": float(s[-1]),
        }

    tool_error_rates = {
        t: round(tool_errors[t] / cnt, 4) if cnt else 0.0
        for t, cnt in tool_calls.items()
    }
    undefined = sorted(set(tool_calls.keys()) - defined_tools) if defined_tools else []
    unused = sorted(defined_tools - set(tool_calls.keys())) if defined_tools else []

    if len(formats) > 1:
        drift_warnings.append(f"Heterogeneous formats in single corpus: {dict(formats)}")
    if "generic" in formats:
        drift_warnings.append(
            f"{formats['generic']} trace(s) fell back to GenericFallbackAdapter — consider adding a MappingAdapter config."
        )
    if len(schema_versions) > 1:
        drift_warnings.append(f"Multiple schema versions detected: {dict(schema_versions)}")
    if undefined:
        drift_warnings.append(f"Tools called that are absent from tool schema: {undefined}")
    if len(sys_prompt_hashes) > 1:
        drift_warnings.append(f"Multiple distinct system prompts detected ({len(sys_prompt_hashes)} variants).")

    return CorpusProfile(
        total_traces=total,
        formats=dict(formats),
        schema_versions=dict(schema_versions),
        models=dict(models),
        outcomes=dict(outcomes),
        unique_system_prompts=len(sys_prompt_hashes),
        turn_stats=turn_stats,
        role_counts=dict(roles),
        tool_call_counts=dict(tool_calls),
        tool_error_counts=dict(tool_errors),
        tool_error_rates=tool_error_rates,
        tool_error_signatures=dict(err_sigs),
        undefined_tools_called=undefined,
        unused_defined_tools=unused,
        extra_key_coverage=dict(extra_keys),
        observation_shapes_by_tool={k: [list(x) for x in sorted(v)] for k, v in obs_shapes.items()},
        tool_arg_shapes={k: [list(x) for x in sorted(v)] for k, v in arg_shapes.items()},
        schema_drift_warnings=drift_warnings,
    )
