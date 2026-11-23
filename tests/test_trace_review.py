"""Comprehensive unit & integration tests for the scalable multi-format trace_review toolkit."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from trace_review.adapters import iter_traces, load_traces
from trace_review.audit import audit_traces
from trace_review.detectors import default_detectors
from trace_review.diff import diff_audits
from trace_review.inspect_view import filter_sessions, render_session_timeline, stratified_sample
from trace_review.profiler import profile_traces
from trace_review.rules import DeclarativeRuleDetector

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACES_PATH = REPO_ROOT / "traces.jsonl"
SCHEMA_PATH = REPO_ROOT / "tools.schema.json"
RULES_PATH = REPO_ROOT / "rules" / "northline_support.json"
MAPPING_EXAMPLE = REPO_ROOT / "schemas" / "custom_mapping_example.json"


def test_atif_corpus_profile_and_audit():
    traces = load_traces(TRACES_PATH, tool_schema_path=SCHEMA_PATH)
    assert len(traces) == 40
    assert all(t.source_format == "atif" for t in traces)

    prof = profile_traces(traces)
    assert prof.total_traces == 40
    assert prof.formats == {"atif": 40}
    assert prof.tool_call_counts["create_refund"] == 30
    assert prof.tool_error_counts["create_refund"] == 20

    dets = default_detectors() + [DeclarativeRuleDetector.from_file(RULES_PATH)]
    report, by_id = audit_traces(traces, detectors=dets, keep_traces=True)
    assert report.total_traces == 40
    # Valid partial refund (t05) should not false-positive
    t05 = next(s for s in report.sessions if s.trace_id == "t05")
    assert t05.findings == []
    # Ineligible refund marked resolved (t13-t15) must be flagged critical
    for tid in ("t13", "t14", "t15"):
        sa = next(s for s in report.sessions if s.trace_id == tid)
        assert "policy.refund_ineligible_order" in sa.finding_codes
    # Phantom refund claims (t19, t22, t28, t40) must be caught
    for tid in ("t19", "t22", "t28", "t40"):
        sa = next(s for s in report.sessions if s.trace_id == tid)
        assert "grounding.phantom_refund_claim" in sa.finding_codes
    # FAQ deflection (t16, t29) and ignored entity (t23, t37) must be caught
    for tid in ("t16", "t29"):
        sa = next(s for s in report.sessions if s.trace_id == tid)
        assert "routing.faq_deflection_with_entity" in sa.finding_codes
    for tid in ("t23", "t37"):
        sa = next(s for s in report.sessions if s.trace_id == tid)
        assert "grounding.ignored_user_entity" in sa.finding_codes

    # HTML dashboard renders cleanly
    html_out = report.to_html(by_id)
    assert "Trace Review Dashboard" in html_out
    assert "t22" in html_out


def test_openai_anthropic_otel_and_custom_mapping_formats(tmp_path: Path):
    # 1. OpenAI Chat Completions format (gzipped JSONL)
    openai_rec = {
        "id": "oa_01",
        "model": "gpt-test",
        "outcome": "failed",
        "messages": [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Refund NL-1001 please"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "create_refund", "arguments": '{"order_id": "NL-1001"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"error": "422 missing amount_cents", "status": 422}'},
            {"role": "assistant", "content": "Your refund has been processed and will arrive in 3-5 days."},
        ],
    }
    gz_path = tmp_path / "openai.jsonl.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(openai_rec) + "\n")

    # 2. Anthropic Messages format
    anth_rec = {
        "id": "an_01",
        "model": "claude-test",
        "system": "Support bot",
        "outcome": "resolved",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Track NL-2002"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Checking now."},
                    {"type": "tool_use", "id": "tu_1", "name": "get_tracking", "input": {"order_id": "NL-2002"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": '{"carrier": "UPS", "eta": "2026-09-01", "last_scan": "Denver", "tracking_number": "1Z999AA10123456784"}',
                    }
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "Your UPS package 1Z999AA10123456784 is in Denver."}]},
        ],
    }
    anth_path = tmp_path / "anthropic.json"
    anth_path.write_text(json.dumps([anth_rec]), encoding="utf-8")

    # 3. OpenTelemetry / OpenInference span format
    otel_rec = {
        "trace_id": "otel_01",
        "outcome": "failed",
        "spans": [
            {
                "span_id": "sp_1",
                "kind": "TOOL",
                "start_time": "2026-09-01T10:00:00Z",
                "attributes": {
                    "tool.name": "lookup_order",
                    "input.value": '{"query": "shoes"}',
                    "output.value": '{"error": "400 unknown argument query"}',
                },
            }
        ],
    }
    otel_path = tmp_path / "otel.json"
    otel_path.write_text(json.dumps(otel_rec), encoding="utf-8")

    # Stream heterogeneous directory in one pass!
    mixed_traces = list(iter_traces(tmp_path, tool_schema_path=SCHEMA_PATH))
    formats = {t.trace_id: t.source_format for t in mixed_traces}
    assert formats == {"oa_01": "openai", "an_01": "anthropic", "otel_01": "otel"}

    dets = default_detectors() + [DeclarativeRuleDetector.from_file(RULES_PATH)]
    report, _ = audit_traces(mixed_traces, detectors=dets)
    oa = next(s for s in report.sessions if s.trace_id == "oa_01")
    assert "tool_schema.missing_required_arg" in oa.finding_codes
    assert "grounding.phantom_refund_claim" in oa.finding_codes

    an = next(s for s in report.sessions if s.trace_id == "an_01")
    assert an.findings == []

    ot = next(s for s in report.sessions if s.trace_id == "otel_01")
    assert "tool_schema.unexpected_arg" in ot.finding_codes

    # 4. Novel custom format via declarative MappingAdapter
    novel_rec = {
        "meta": {"conversation_id": "novel_99", "bot_name": "cx-v2", "model": "gemini-4"},
        "result": {"status": "failed"},
        "events": [
            {"actor": "customer", "text": "Refund NL-5555", "ts": "2026-09-01T00:00:00Z"},
            {
                "actor": "bot",
                "text": "Calling refund.",
                "actions": [{"id": "a1", "tool": "create_refund", "params": {"order_id": "NL-5555"}}],
                "outputs": [{"action_id": "a1", "payload": {"error": "422 missing amount_cents"}}],
            },
        ],
    }
    novel_path = tmp_path / "novel.jsonl"
    novel_path.write_text(json.dumps(novel_rec) + "\n", encoding="utf-8")
    novel_traces = load_traces(novel_path, tool_schema_path=SCHEMA_PATH, mapping_config_path=MAPPING_EXAMPLE)
    assert len(novel_traces) == 1
    assert novel_traces[0].trace_id == "novel_99"
    assert novel_traces[0].source_format == "custom_support_log_v1"
    rep_novel, _ = audit_traces(novel_traces, detectors=dets)
    assert "tool_schema.missing_required_arg" in rep_novel.sessions[0].finding_codes


def test_inspect_slicing_and_regression_diff():
    traces = load_traces(TRACES_PATH, tool_schema_path=SCHEMA_PATH)
    dets = default_detectors() + [DeclarativeRuleDetector.from_file(RULES_PATH)]
    base_rep, by_id = audit_traces(traces, detectors=dets, keep_traces=True)

    # Filter & stratified sample
    crit = filter_sessions(base_rep, by_id, min_severity="critical")
    assert len(crit) >= 6
    sampled = stratified_sample(crit, n=3)
    assert len(sampled) == 3
    rendered = render_session_timeline(*sampled[0])
    assert "SESSION:" in rendered

    # Diff baseline (all 40) against clean-only subset (simulating post-fix candidate)
    clean_traces = [by_id[s.trace_id] for s in base_rep.sessions if not s.findings]
    cand_rep, _ = audit_traces(clean_traces, detectors=dets)
    diff = diff_audits(base_rep, cand_rep)
    assert diff.candidate_flagged_rate == 0.0
    assert any(d.status == "resolved" for d in diff.code_deltas)
    assert "Trace Regression Diff Report" in diff.to_markdown()
