"""Audit orchestration, taxonomy aggregation, co-occurrence analysis, and Markdown/JSON/HTML reporting."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .detectors import TraceDetector, default_detectors
from .model import CanonicalTrace, Finding

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class SessionAudit:
    """Audit result for a single trace/session."""

    trace_id: str
    source_format: str
    outcome: Optional[str]
    turn_count: int
    tool_call_count: int
    tool_error_count: int
    findings: list[Finding] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def max_severity(self) -> str:
        if not self.findings:
            return "clean"
        return min(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 99)).severity

    @property
    def finding_codes(self) -> list[str]:
        return sorted({f.code for f in self.findings})

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "source_format": self.source_format,
            "outcome": self.outcome,
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
            "tool_error_count": self.tool_error_count,
            "max_severity": self.max_severity,
            "finding_codes": self.finding_codes,
            "findings": [f.to_dict() for f in self.findings],
            "extra": self.extra,
        }


@dataclass
class AuditReport:
    """Corpus-wide audit report with taxonomy, outcome correlation, co-occurrence, and per-session cards."""

    total_traces: int
    traces_with_findings: int
    clean_traces: int
    outcomes: dict[str, int]
    severity_session_counts: dict[str, int]
    code_stats: dict[str, dict[str, Any]]
    category_session_counts: dict[str, int]
    outcome_by_code: dict[str, dict[str, int]]
    cooccurrence_pairs: list[dict[str, Any]]
    sessions: list[SessionAudit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_traces": self.total_traces,
            "traces_with_findings": self.traces_with_findings,
            "clean_traces": self.clean_traces,
            "outcomes": self.outcomes,
            "severity_session_counts": self.severity_session_counts,
            "code_stats": self.code_stats,
            "category_session_counts": self.category_session_counts,
            "outcome_by_code": self.outcome_by_code,
            "cooccurrence_pairs": self.cooccurrence_pairs,
            "sessions": [s.to_dict() for s in self.sessions],
        }

    def to_markdown(self) -> str:
        pct_flagged = (100.0 * self.traces_with_findings / self.total_traces) if self.total_traces else 0.0
        lines = [
            "# Trace Audit Report",
            "",
            f"- **Total traces audited**: {self.total_traces}",
            f"- **Traces with findings**: {self.traces_with_findings} ({pct_flagged:.1f}%)",
            f"- **Clean traces**: {self.clean_traces}",
            f"- **Outcomes**: {self.outcomes}",
            f"- **Sessions by max severity**: {self.severity_session_counts}",
            "",
            "## Failure Taxonomy (Sorted by Affected Sessions)",
            "",
            "| Finding Code | Category | Severity | Sessions | % Corpus | Total Hits | Outcomes | Sample Sessions |",
            "|---|---|---|---:|---:|---:|---|---|",
        ]
        sorted_codes = sorted(
            self.code_stats.items(),
            key=lambda kv: (-kv[1]["sessions"], SEVERITY_ORDER.get(kv[1]["severity"], 99), kv[0]),
        )
        for code, st in sorted_codes:
            pct = (100.0 * st["sessions"] / self.total_traces) if self.total_traces else 0.0
            outs = ", ".join(f"{k}:{v}" for k, v in sorted(self.outcome_by_code.get(code, {}).items()))
            samples = ", ".join(st["sample_sessions"][:5])
            lines.append(
                f"| `{code}` | {st['category']} | **{st['severity']}** | {st['sessions']} | {pct:.1f}% | "
                f"{st['total_hits']} | {outs} | {samples} |"
            )

        if self.cooccurrence_pairs:
            lines.extend([
                "",
                "## Top Co-Occurring Failure Pairs",
                "",
                "| Finding A | Finding B | Shared Sessions |",
                "|---|---|---:|",
            ])
            for pair in self.cooccurrence_pairs[:12]:
                lines.append(f"| `{pair['code_a']}` | `{pair['code_b']}` | {pair['sessions']} |")

        lines.extend([
            "",
            "## Per-Session Summary",
            "",
            "| Session | Outcome | Max Severity | Turns | Tool Calls (Errs) | Findings |",
            "|---|---|---|---:|---:|---|",
        ])
        for s in self.sessions:
            codes_str = ", ".join(f"`{c}`" for c in s.finding_codes) if s.finding_codes else "_clean_"
            lines.append(
                f"| `{s.trace_id}` | `{s.outcome or 'none'}` | {s.max_severity} | "
                f"{s.turn_count} | {s.tool_call_count} ({s.tool_error_count}) | {codes_str} |"
            )

        return "\n".join(lines) + "\n"

    def to_html(self, traces_by_id: Optional[dict[str, CanonicalTrace]] = None) -> str:
        """Render a self-contained, zero-dependency interactive HTML trace review dashboard."""
        payload = {
            "summary": {
                "total_traces": self.total_traces,
                "traces_with_findings": self.traces_with_findings,
                "clean_traces": self.clean_traces,
                "outcomes": self.outcomes,
                "code_stats": self.code_stats,
                "outcome_by_code": self.outcome_by_code,
            },
            "sessions": [],
        }
        for s in self.sessions:
            item = s.to_dict()
            if traces_by_id and s.trace_id in traces_by_id:
                tr = traces_by_id[s.trace_id]
                item["turns"] = [
                    {
                        "index": t.index,
                        "role": t.role,
                        "content": t.content[:1500],
                        "tool_calls": [
                            {"id": tc.call_id, "name": tc.name, "arguments": tc.arguments}
                            for tc in t.tool_calls
                        ],
                        "tool_results": [
                            {
                                "id": r.call_id,
                                "tool_name": r.tool_name,
                                "is_error": r.is_error,
                                "status_code": r.status_code,
                                "content": r.parsed_content if r.parsed_content is not None else r.raw_content,
                            }
                            for r in t.tool_results
                        ],
                    }
                    for t in tr.turns
                    if t.role != "system"
                ]
            payload["sessions"].append(item)

        data_json = json.dumps(payload).replace("</", "<\\/")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trace Review Dashboard</title>
<style>
  :root {{ --bg:#0f172a; --panel:#1e293b; --muted:#94a3b8; --text:#f1f5f9; --border:#334155;
           --crit:#ef4444; --high:#f97316; --med:#eab308; --low:#38bdf8; --ok:#22c55e; }}
  body {{ margin:0; font-family: system-ui, -apple-system, sans-serif; background:var(--bg); color:var(--text); }}
  header {{ padding:16px 24px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }}
  .layout {{ display:grid; grid-template-columns: 360px 1fr; height: calc(100vh - 65px); }}
  .sidebar {{ border-right:1px solid var(--border); overflow-y:auto; padding:12px; }}
  .main {{ overflow-y:auto; padding:20px; }}
  .controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }}
  select, input {{ background:var(--panel); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px 8px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin-bottom:8px; cursor:pointer; }}
  .card:hover, .card.active {{ border-color:#60a5fa; }}
  .badge {{ display:inline-block; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:600; margin-right:4px; }}
  .sev-critical {{ background:rgba(239,68,68,.2); color:#fca5a5; }}
  .sev-high {{ background:rgba(249,115,22,.2); color:#fdba74; }}
  .sev-medium {{ background:rgba(234,179,8,.2); color:#fde047; }}
  .sev-low {{ background:rgba(56,189,248,.2); color:#7dd3fc; }}
  .sev-clean {{ background:rgba(34,197,94,.2); color:#86efac; }}
  .turn {{ background:var(--panel); border-left:3px solid var(--border); border-radius:6px; padding:10px 12px; margin:10px 0; }}
  .turn.user {{ border-left-color:#38bdf8; }}
  .turn.agent {{ border-left-color:#a78bfa; }}
  .turn.err {{ border-left-color:var(--crit); }}
  pre {{ background:#0b1220; padding:8px; border-radius:6px; overflow-x:auto; font-size:12px; }}
  .grid-kpi {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; margin-bottom:16px; }}
  .kpi {{ background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:12px; }}
  .kpi h4 {{ margin:0 0 6px; color:var(--muted); font-size:12px; text-transform:uppercase; }}
  .kpi div {{ font-size:22px; font-weight:700; }}
</style>
</head>
<body>
<header>
  <div><strong>Trace Review Dashboard</strong> <span style="color:var(--muted)">Scalable Multi-Format Audit UI</span></div>
  <div id="statsBar" style="color:var(--muted);font-size:13px;"></div>
</header>
<div class="layout">
  <div class="sidebar">
    <div class="controls">
      <input id="searchBox" type="text" placeholder="Filter session / code..." style="flex:1">
      <select id="codeFilter"><option value="">All findings</option></select>
      <select id="outcomeFilter"><option value="">All outcomes</option></select>
    </div>
    <div id="sessionList"></div>
  </div>
  <div class="main" id="detailPane"></div>
</div>
<script>
const DATA = {data_json};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
document.getElementById("statsBar").textContent =
  `${{DATA.summary.total_traces}} traces · ${{DATA.summary.traces_with_findings}} flagged · ${{DATA.summary.clean_traces}} clean`;

const codeSel = document.getElementById("codeFilter");
Object.entries(DATA.summary.code_stats).sort((a,b) => b[1].sessions - a[1].sessions).forEach(([c, st]) => {{
  const o = document.createElement("option");
  o.value = c; o.textContent = `${{c}} (${{st.sessions}})`;
  codeSel.appendChild(o);
}});
const outSel = document.getElementById("outcomeFilter");
Object.entries(DATA.summary.outcomes).forEach(([k, v]) => {{
  const o = document.createElement("option");
  o.value = k; o.textContent = `${{k}} (${{v}})`;
  outSel.appendChild(o);
}});

let activeId = null;
function renderList() {{
  const q = document.getElementById("searchBox").value.toLowerCase();
  const cf = codeSel.value;
  const of = outSel.value;
  const list = document.getElementById("sessionList");
  list.innerHTML = "";
  DATA.sessions.filter(s => {{
    if (cf && !s.finding_codes.includes(cf)) return false;
    if (of && (s.outcome || "(none)") !== of) return false;
    if (q && !(s.trace_id.toLowerCase().includes(q) || s.finding_codes.join(" ").toLowerCase().includes(q))) return false;
    return true;
  }}).forEach(s => {{
    const div = document.createElement("div");
    div.className = "card" + (s.trace_id === activeId ? " active" : "");
    div.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong>${{esc(s.trace_id)}}</strong>
        <span class="badge sev-${{esc(s.max_severity)}}">${{esc(s.max_severity)}}</span>
      </div>
      <div style="font-size:12px;color:var(--muted);margin:4px 0">
        outcome: <code>${{esc(s.outcome || "none")}}</code> · turns: ${{s.turn_count}} · tools: ${{s.tool_call_count}} (err: ${{s.tool_error_count}})
      </div>
      <div>${{s.finding_codes.slice(0,4).map(c => `<span class="badge" style="background:#334155">${{esc(c)}}</span>`).join("")}}</div>`;
    div.onclick = () => {{ activeId = s.trace_id; renderList(); renderDetail(s); }};
    list.appendChild(div);
  }});
}}

function renderOverview() {{
  const pane = document.getElementById("detailPane");
  const rows = Object.entries(DATA.summary.code_stats)
    .sort((a,b) => b[1].sessions - a[1].sessions)
    .map(([c, st]) => `<tr><td><code>${{esc(c)}}</code></td><td>${{esc(st.category)}}</td><td><span class="badge sev-${{esc(st.severity)}}">${{esc(st.severity)}}</span></td><td>${{st.sessions}}</td><td>${{st.total_hits}}</td></tr>`).join("");
  pane.innerHTML = `
    <h2>Corpus Overview</h2>
    <div class="grid-kpi">
      <div class="kpi"><h4>Total Traces</h4><div>${{DATA.summary.total_traces}}</div></div>
      <div class="kpi"><h4>Flagged</h4><div style="color:var(--high)">${{DATA.summary.traces_with_findings}}</div></div>
      <div class="kpi"><h4>Clean</h4><div style="color:var(--ok)">${{DATA.summary.clean_traces}}</div></div>
    </div>
    <h3>Failure Taxonomy</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="text-align:left;border-bottom:1px solid var(--border)"><th>Code</th><th>Category</th><th>Severity</th><th>Sessions</th><th>Hits</th></tr></thead>
      <tbody>${{rows}}</tbody>
    </table>
    <p style="color:var(--muted);margin-top:16px">Select a session from the left sidebar to inspect its timeline and inline findings.</p>`;
}}

function renderDetail(s) {{
  const pane = document.getElementById("detailPane");
  const fHtml = s.findings.map(f => `
    <div class="card" style="cursor:default">
      <span class="badge sev-${{esc(f.severity)}}">${{esc(f.severity)}}</span>
      <code>${{esc(f.code)}}</code> <span style="color:var(--muted)">steps: ${{esc(JSON.stringify(f.step_indices))}}</span>
      <div style="margin-top:6px">${{esc(f.message)}}</div>
      <pre>${{esc(JSON.stringify(f.evidence, null, 2))}}</pre>
    </div>`).join("") || "<p>No findings detected.</p>";

  const tHtml = (s.turns || []).map(t => {{
    const calls = t.tool_calls.map(tc => `<pre>CALL ${{esc(tc.name)}}(${{esc(JSON.stringify(tc.arguments))}})</pre>`).join("");
    const ress = t.tool_results.map(r => `<pre style="border-left:3px solid ${{r.is_error ? 'var(--crit)' : 'var(--ok)'}}">OBS [${{esc(r.tool_name || r.id)}}]${{r.is_error ? ' ERROR' : ''}}: ${{esc(JSON.stringify(r.content))}}</pre>`).join("");
    return `<div class="turn ${{esc(t.role)}}">
      <div style="font-size:12px;color:var(--muted)">Step ${{t.index}} · <strong>${{esc(t.role.toUpperCase())}}</strong></div>
      ${{t.content ? `<div style="margin:6px 0;white-space:pre-wrap">${{esc(t.content)}}</div>` : ""}}
      ${{calls}}${{ress}}
    </div>`;
  }}).join("");

  pane.innerHTML = `
    <button onclick="activeId=null;renderList();renderOverview()" style="background:var(--panel);color:var(--text);border:1px solid var(--border);padding:5px 10px;border-radius:6px;cursor:pointer;margin-bottom:12px">← Overview</button>
    <h2>Session ${{esc(s.trace_id)}} <span class="badge sev-${{esc(s.max_severity)}}">${{esc(s.max_severity)}}</span></h2>
    <div style="color:var(--muted);margin-bottom:12px">format=${{esc(s.source_format)}} · outcome=${{esc(s.outcome)}} · turns=${{s.turn_count}} · tool_calls=${{s.tool_call_count}} · tool_errors=${{s.tool_error_count}}</div>
    <h3>Findings (${{s.findings.length}})</h3>${{fHtml}}
    <h3>Timeline</h3>${{tHtml}}`;
}}

["searchBox","codeFilter","outcomeFilter"].forEach(id => document.getElementById(id).addEventListener("input", renderList));
renderList();
renderOverview();
</script>
</body>
</html>
"""


def audit_traces(
    traces: Iterable[CanonicalTrace],
    detectors: Optional[list[TraceDetector]] = None,
    keep_traces: bool = False,
) -> tuple[AuditReport, dict[str, CanonicalTrace]]:
    """Run all detectors across a stream of CanonicalTraces and aggregate an AuditReport."""
    active_detectors = detectors if detectors is not None else default_detectors()
    sessions: list[SessionAudit] = []
    traces_by_id: dict[str, CanonicalTrace] = {}

    outcomes: Counter[str] = Counter()
    sev_sessions: Counter[str] = Counter()
    cat_sessions: Counter[str] = Counter()
    code_hits: Counter[str] = Counter()
    code_sessions: dict[str, list[str]] = defaultdict(list)
    code_meta: dict[str, tuple[str, str]] = {}
    outcome_by_code: dict[str, Counter[str]] = defaultdict(Counter)
    cooccur: Counter[tuple[str, str]] = Counter()

    for trace in traces:
        if keep_traces:
            traces_by_id[trace.trace_id] = trace

        findings: list[Finding] = []
        for det in active_detectors:
            findings.extend(det.detect(trace))

        # Sort findings by severity then earliest step
        findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 99), f.step_indices[0] if f.step_indices else -1, f.code))

        pairs = trace.tool_call_pairs()
        err_count = sum(1 for _, tr in pairs if tr is not None and tr.is_error)
        sa = SessionAudit(
            trace_id=trace.trace_id,
            source_format=trace.source_format,
            outcome=trace.outcome,
            turn_count=len(trace.turns),
            tool_call_count=len(pairs),
            tool_error_count=err_count,
            findings=findings,
            extra={k: v for k, v in trace.extra.items() if k in {"opened_at", "tags_gold"}},
        )
        sessions.append(sa)

        out_label = trace.outcome or "(none)"
        outcomes[out_label] += 1
        sev_sessions[sa.max_severity] += 1

        unique_codes = sorted({f.code for f in findings})
        unique_cats = {f.category for f in findings}
        for cat in unique_cats:
            cat_sessions[cat] += 1
        for f in findings:
            code_hits[f.code] += 1
            if f.code not in code_meta or SEVERITY_ORDER.get(f.severity, 99) < SEVERITY_ORDER.get(code_meta[f.code][1], 99):
                code_meta[f.code] = (f.category, f.severity)
        for c in unique_codes:
            code_sessions[c].append(trace.trace_id)
            outcome_by_code[c][out_label] += 1
        for i in range(len(unique_codes)):
            for j in range(i + 1, len(unique_codes)):
                cooccur[(unique_codes[i], unique_codes[j])] += 1

    code_stats: dict[str, dict[str, Any]] = {}
    for code, sess_ids in code_sessions.items():
        cat, sev = code_meta[code]
        code_stats[code] = {
            "category": cat,
            "severity": sev,
            "sessions": len(sess_ids),
            "total_hits": code_hits[code],
            "sample_sessions": sess_ids[:10],
        }

    cooccurrence_pairs = [
        {"code_a": a, "code_b": b, "sessions": cnt}
        for (a, b), cnt in cooccur.most_common(25)
    ]

    flagged = sum(1 for s in sessions if s.findings)
    report = AuditReport(
        total_traces=len(sessions),
        traces_with_findings=flagged,
        clean_traces=len(sessions) - flagged,
        outcomes=dict(outcomes),
        severity_session_counts=dict(sev_sessions),
        code_stats=code_stats,
        category_session_counts=dict(cat_sessions),
        outcome_by_code={k: dict(v) for k, v in outcome_by_code.items()},
        cooccurrence_pairs=cooccurrence_pairs,
        sessions=sessions,
    )
    return report, traces_by_id
