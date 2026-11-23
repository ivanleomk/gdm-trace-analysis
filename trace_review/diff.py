"""Cohort / regression diffing between two audited trace runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .audit import AuditReport


@dataclass
class CodeDelta:
    code: str
    severity: str
    baseline_sessions: int
    baseline_rate: float
    candidate_sessions: int
    candidate_rate: float
    rate_delta: float
    status: str  # regressed | improved | unchanged | new | resolved


@dataclass
class DiffReport:
    baseline_total: int
    candidate_total: int
    baseline_flagged_rate: float
    candidate_flagged_rate: float
    outcome_deltas: dict[str, dict[str, float]]
    code_deltas: list[CodeDelta] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_total": self.baseline_total,
            "candidate_total": self.candidate_total,
            "baseline_flagged_rate": self.baseline_flagged_rate,
            "candidate_flagged_rate": self.candidate_flagged_rate,
            "outcome_deltas": self.outcome_deltas,
            "code_deltas": [asdict(d) for d in self.code_deltas],
        }

    def to_markdown(self) -> str:
        delta_flag = (self.candidate_flagged_rate - self.baseline_flagged_rate) * 100.0
        lines = [
            "# Trace Regression Diff Report",
            "",
            f"- **Baseline traces**: {self.baseline_total} (flagged: {self.baseline_flagged_rate*100:.1f}%)",
            f"- **Candidate traces**: {self.candidate_total} (flagged: {self.candidate_flagged_rate*100:.1f}%, delta: {delta_flag:+.1f} pp)",
            "",
            "## Outcome Deltas",
            "",
            "| Outcome | Baseline % | Candidate % | Delta (pp) |",
            "|---|---:|---:|---:|",
        ]
        for out, d in sorted(self.outcome_deltas.items()):
            lines.append(
                f"| `{out}` | {d['baseline_rate']*100:.1f}% | {d['candidate_rate']*100:.1f}% | {d['delta']*100:+.1f} |"
            )

        lines.extend([
            "",
            "## Finding Rate Deltas",
            "",
            "| Finding Code | Severity | Baseline | Candidate | Delta (pp) | Status |",
            "|---|---|---:|---:|---:|---|",
        ])
        for cd in self.code_deltas:
            lines.append(
                f"| `{cd.code}` | {cd.severity} | {cd.baseline_sessions} ({cd.baseline_rate*100:.1f}%) | "
                f"{cd.candidate_sessions} ({cd.candidate_rate*100:.1f}%) | {cd.rate_delta*100:+.1f} | **{cd.status}** |"
            )
        return "\n".join(lines) + "\n"


def diff_audits(baseline: AuditReport, candidate: AuditReport) -> DiffReport:
    """Compare two AuditReports and quantify regressions vs improvements."""
    b_tot = max(baseline.total_traces, 1)
    c_tot = max(candidate.total_traces, 1)

    all_outcomes = sorted(set(baseline.outcomes.keys()) | set(candidate.outcomes.keys()))
    outcome_deltas: dict[str, dict[str, float]] = {}
    for o in all_outcomes:
        br = baseline.outcomes.get(o, 0) / b_tot
        cr = candidate.outcomes.get(o, 0) / c_tot
        outcome_deltas[o] = {
            "baseline_rate": round(br, 4),
            "candidate_rate": round(cr, 4),
            "delta": round(cr - br, 4),
        }

    all_codes = sorted(set(baseline.code_stats.keys()) | set(candidate.code_stats.keys()))
    deltas: list[CodeDelta] = []
    for code in all_codes:
        bs = baseline.code_stats.get(code)
        cs = candidate.code_stats.get(code)
        b_cnt = bs["sessions"] if bs else 0
        c_cnt = cs["sessions"] if cs else 0
        b_rate = b_cnt / b_tot
        c_rate = c_cnt / c_tot
        diff = c_rate - b_rate
        sev = (cs or bs)["severity"]

        if b_cnt == 0 and c_cnt > 0:
            status = "new"
        elif b_cnt > 0 and c_cnt == 0:
            status = "resolved"
        elif abs(diff) < 1e-6:
            status = "unchanged"
        elif diff > 0:
            status = "regressed"
        else:
            status = "improved"

        deltas.append(
            CodeDelta(
                code=code,
                severity=sev,
                baseline_sessions=b_cnt,
                baseline_rate=round(b_rate, 4),
                candidate_sessions=c_cnt,
                candidate_rate=round(c_rate, 4),
                rate_delta=round(diff, 4),
                status=status,
            )
        )

    deltas.sort(key=lambda d: (-abs(d.rate_delta), d.code))
    return DiffReport(
        baseline_total=baseline.total_traces,
        candidate_total=candidate.total_traces,
        baseline_flagged_rate=round(baseline.traces_with_findings / b_tot, 4),
        candidate_flagged_rate=round(candidate.traces_with_findings / c_tot, 4),
        outcome_deltas=outcome_deltas,
        code_deltas=deltas,
    )
