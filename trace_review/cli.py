"""Unified CLI for trace-profile, trace-audit, trace-inspect, and trace-diff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .adapters import iter_traces
from .audit import audit_traces
from .detectors import TraceDetector, default_detectors, load_plugin_detectors
from .diff import diff_audits
from .inspect_view import filter_sessions, render_session_timeline, stratified_sample
from .profiler import profile_traces
from .rules import DeclarativeRuleDetector


def _add_common_input_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("inputs", nargs="+", help="Trace file(s), directory(ies), .gz files, or '-' for stdin.")
    p.add_argument("--format", default="auto", help="Format adapter: auto, atif, openai, anthropic, otel, generic.")
    p.add_argument("--tool-schema", default=None, help="Optional external JSON Schema file (e.g. tools.schema.json).")
    p.add_argument("--mapping", default=None, help="Optional declarative MappingAdapter JSON config for novel formats.")


def _add_detector_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rules", action="append", default=[], help="Declarative policy rule JSON file (repeatable).")
    p.add_argument("--plugin", action="append", default=[], help="Custom Python TraceDetector plugin path (repeatable).")


def _build_detectors(rules_paths: list[str], plugin_paths: list[str]) -> list[TraceDetector]:
    dets: list[TraceDetector] = default_detectors()
    for rp in rules_paths:
        dets.append(DeclarativeRuleDetector.from_file(rp))
    for pp in plugin_paths:
        dets.extend(load_plugin_detectors(pp))
    return dets


def cmd_profile(args: argparse.Namespace) -> int:
    stream = iter_traces(
        args.inputs,
        format_name=args.format,
        tool_schema_path=args.tool_schema,
        mapping_config_path=args.mapping,
    )
    prof = profile_traces(stream)
    out = json.dumps(prof.to_dict(), indent=2) if args.json else prof.to_markdown()
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    stream = iter_traces(
        args.inputs,
        format_name=args.format,
        tool_schema_path=args.tool_schema,
        mapping_config_path=args.mapping,
    )
    dets = _build_detectors(args.rules, args.plugin)
    report, traces_by_id = audit_traces(stream, detectors=dets, keep_traces=bool(args.html))

    if args.html:
        Path(args.html).write_text(report.to_html(traces_by_id), encoding="utf-8")

    out = json.dumps(report.to_dict(), indent=2) if args.json else report.to_markdown()
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    stream = iter_traces(
        args.inputs,
        format_name=args.format,
        tool_schema_path=args.tool_schema,
        mapping_config_path=args.mapping,
    )
    dets = _build_detectors(args.rules, args.plugin)
    report, traces_by_id = audit_traces(stream, detectors=dets, keep_traces=True)

    matched = filter_sessions(
        report,
        traces_by_id,
        session_ids=args.session or None,
        finding_code=args.finding,
        min_severity=args.min_severity,
        outcome=args.outcome,
        tool_name=args.tool,
        only_errors=args.only_errors,
    )
    if args.sample:
        matched = stratified_sample(matched, args.sample, seed=args.seed)
    if args.limit:
        matched = matched[: args.limit]

    if args.export_jsonl:
        with Path(args.export_jsonl).open("w", encoding="utf-8") as f:
            for sa, tr in matched:
                rec = tr.to_dict()
                rec["audit"] = sa.to_dict()
                f.write(json.dumps(rec) + "\n")

    if not matched:
        sys.stdout.write("No sessions matched the filter criteria.\n")
        return 0

    rendered = [
        render_session_timeline(sa, tr, max_chars=args.max_chars, include_system=args.include_system)
        for sa, tr in matched
    ]
    sys.stdout.write(f"Matched {len(matched)} session(s):\n\n" + "\n\n".join(rendered) + "\n")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    dets = _build_detectors(args.rules, args.plugin)
    base_stream = iter_traces(
        args.baseline,
        format_name=args.format,
        tool_schema_path=args.tool_schema,
        mapping_config_path=args.mapping,
    )
    cand_stream = iter_traces(
        args.candidate,
        format_name=args.format,
        tool_schema_path=args.tool_schema,
        mapping_config_path=args.mapping,
    )
    base_rep, _ = audit_traces(base_stream, detectors=dets)
    cand_rep, _ = audit_traces(cand_stream, detectors=dets)
    diff = diff_audits(base_rep, cand_rep)
    out = json.dumps(diff.to_dict(), indent=2) if args.json else diff.to_markdown()
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trace-review",
        description="Scalable multi-format agent trace profiling, auditing, inspection, and diffing toolkit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prof = sub.add_parser("profile", help="Single-pass streaming schema & corpus discovery.")
    _add_common_input_args(p_prof)
    p_prof.add_argument("--json", action="store_true", help="Output JSON instead of Markdown.")
    p_prof.add_argument("--out", default=None, help="Write output to file instead of stdout.")
    p_prof.set_defaults(func=cmd_profile)

    p_aud = sub.add_parser("audit", help="Run universal detectors + domain policy rules across traces.")
    _add_common_input_args(p_aud)
    _add_detector_args(p_aud)
    p_aud.add_argument("--json", action="store_true", help="Output JSON instead of Markdown.")
    p_aud.add_argument("--out", default=None, help="Write Markdown/JSON report to file.")
    p_aud.add_argument("--html", default=None, help="Generate interactive self-contained HTML review dashboard.")
    p_aud.set_defaults(func=cmd_audit)

    p_insp = sub.add_parser("inspect", help="Slice, stratified-sample, and inspect matching sessions.")
    _add_common_input_args(p_insp)
    _add_detector_args(p_insp)
    p_insp.add_argument("--session", action="append", default=[], help="Filter to specific session/trace ID (repeatable).")
    p_insp.add_argument("--finding", default=None, help="Substring filter on finding code (e.g. phantom_refund).")
    p_insp.add_argument("--min-severity", choices=["critical", "high", "medium", "low", "info"], default=None)
    p_insp.add_argument("--outcome", default=None, help="Filter by session outcome (e.g. resolved, escalated, failed).")
    p_insp.add_argument("--tool", default=None, help="Filter to sessions invoking a specific tool.")
    p_insp.add_argument("--only-errors", action="store_true", help="Only sessions with >=1 tool error.")
    p_insp.add_argument("--sample", type=int, default=None, help="Stratified sample size across failure codes.")
    p_insp.add_argument("--seed", type=int, default=42, help="Random seed for stratified sampling.")
    p_insp.add_argument("--limit", type=int, default=None, help="Max sessions to print.")
    p_insp.add_argument("--max-chars", type=int, default=220, help="Truncate long messages/payloads.")
    p_insp.add_argument("--include-system", action="store_true", help="Include system prompt step in output.")
    p_insp.add_argument("--export-jsonl", default=None, help="Export matched canonical traces + findings to JSONL.")
    p_insp.set_defaults(func=cmd_inspect)

    p_diff = sub.add_parser("diff", help="Compare two trace cohorts for regressions and improvements.")
    p_diff.add_argument("baseline", help="Baseline trace file or directory.")
    p_diff.add_argument("candidate", help="Candidate trace file or directory.")
    p_diff.add_argument("--format", default="auto")
    p_diff.add_argument("--tool-schema", default=None)
    p_diff.add_argument("--mapping", default=None)
    _add_detector_args(p_diff)
    p_diff.add_argument("--json", action="store_true")
    p_diff.add_argument("--out", default=None)
    p_diff.set_defaults(func=cmd_diff)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def main_profile() -> int:
    return main(["profile", *sys.argv[1:]])


def main_audit() -> int:
    return main(["audit", *sys.argv[1:]])


def main_inspect() -> int:
    return main(["inspect", *sys.argv[1:]])


def main_diff() -> int:
    return main(["diff", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
