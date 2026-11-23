"""Targeted session slicer, stratified sampler, and compact timeline viewer."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from typing import Any, Optional

from .audit import SEVERITY_ORDER, AuditReport, SessionAudit
from .model import CanonicalTrace


def filter_sessions(
    report: AuditReport,
    traces_by_id: dict[str, CanonicalTrace],
    session_ids: Optional[list[str]] = None,
    finding_code: Optional[str] = None,
    min_severity: Optional[str] = None,
    outcome: Optional[str] = None,
    tool_name: Optional[str] = None,
    only_errors: bool = False,
) -> list[tuple[SessionAudit, CanonicalTrace]]:
    """Slice audited sessions by finding, severity, outcome, tool, or explicit session IDs."""
    id_set = set(session_ids) if session_ids else None
    min_rank = SEVERITY_ORDER.get(min_severity, 99) if min_severity else None

    matched: list[tuple[SessionAudit, CanonicalTrace]] = []
    for sa in report.sessions:
        tr = traces_by_id.get(sa.trace_id)
        if tr is None:
            continue
        if id_set is not None and sa.trace_id not in id_set:
            continue
        if outcome is not None and (sa.outcome or "(none)") != outcome:
            continue
        if finding_code is not None:
            if not any(finding_code in c for c in sa.finding_codes):
                continue
        if min_rank is not None:
            if not sa.findings or SEVERITY_ORDER.get(sa.max_severity, 99) > min_rank:
                continue
        if tool_name is not None:
            if not any(tc.name == tool_name for tc in tr.all_tool_calls()):
                continue
        if only_errors and sa.tool_error_count == 0:
            continue
        matched.append((sa, tr))
    return matched


def stratified_sample(
    items: list[tuple[SessionAudit, CanonicalTrace]],
    n: int,
    seed: int = 42,
) -> list[tuple[SessionAudit, CanonicalTrace]]:
    """Select up to `n` sessions maximizing coverage across distinct primary failure codes."""
    if n <= 0 or len(items) <= n:
        return items

    rng = random.Random(seed)
    buckets: dict[str, list[tuple[SessionAudit, CanonicalTrace]]] = defaultdict(list)
    for sa, tr in items:
        key = sa.findings[0].code if sa.findings else "_clean_"
        buckets[key].append((sa, tr))

    for b in buckets.values():
        rng.shuffle(b)

    selected: list[tuple[SessionAudit, CanonicalTrace]] = []
    keys = sorted(buckets.keys())
    while len(selected) < n and any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k] and len(selected) < n:
                selected.append(buckets[k].pop())
    return selected


def render_session_timeline(
    sa: SessionAudit,
    trace: CanonicalTrace,
    max_chars: int = 220,
    include_system: bool = False,
) -> str:
    """Render a compact, readable ASCII timeline of one session with inline findings."""
    lines = [
        "=" * 78,
        f"SESSION: {sa.trace_id} | format={sa.source_format} | outcome={sa.outcome} | "
        f"severity={sa.max_severity} | turns={sa.turn_count} | tools={sa.tool_call_count} (err={sa.tool_error_count})",
        "-" * 78,
    ]

    findings_by_step: dict[int, list[str]] = defaultdict(list)
    if sa.findings:
        lines.append("FINDINGS:")
        for f in sa.findings:
            steps_s = ",".join(str(x) for x in f.step_indices) if f.step_indices else "-"
            lines.append(f"  [{f.severity.upper()}] {f.code} (steps={steps_s}): {f.message}")
            for s_idx in f.step_indices:
                findings_by_step[s_idx].append(f"[{f.severity.upper()}] {f.code}")
        lines.append("-" * 78)
    else:
        lines.append("FINDINGS: (none)")
        lines.append("-" * 78)

    for turn in trace.turns:
        if turn.role == "system" and not include_system:
            continue
        marker = f"  <-- {' ; '.join(findings_by_step[turn.index])}" if turn.index in findings_by_step else ""
        header = f"[Step {turn.index:02d}] {turn.role.upper()}{marker}"
        lines.append(header)
        if turn.content.strip():
            txt = " ".join(turn.content.strip().split())
            if len(txt) > max_chars:
                txt = txt[: max_chars - 3] + "..."
            lines.append(f"    MSG: {txt}")
        for tc in turn.tool_calls:
            args_s = json.dumps(tc.arguments, sort_keys=True) if isinstance(tc.arguments, (dict, list)) else repr(tc.arguments)
            if len(args_s) > max_chars:
                args_s = args_s[: max_chars - 3] + "..."
            lines.append(f"    CALL -> {tc.name}({args_s})")
        for tr in turn.tool_results:
            obs_s = json.dumps(tr.parsed_content, sort_keys=True) if isinstance(tr.parsed_content, (dict, list)) else str(tr.raw_content)
            if len(obs_s) > max_chars:
                obs_s = obs_s[: max_chars - 3] + "..."
            tag = f"ERR(HTTP {tr.status_code})" if (tr.is_error and tr.status_code) else ("ERR" if tr.is_error else "OK")
            lines.append(f"    OBS  <- [{tr.tool_name or tr.call_id}] {tag}: {obs_s}")

    return "\n".join(lines)
