"""Scalable, format-agnostic agent trace analysis and review toolkit."""

from .model import (
    CanonicalTrace,
    CanonicalTurn,
    Finding,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from .adapters import AdapterRegistry, iter_traces, load_traces
from .audit import AuditReport, audit_traces
from .profiler import CorpusProfile, profile_traces
from .diff import DiffReport, diff_audits

__all__ = [
    "AdapterRegistry",
    "AuditReport",
    "CanonicalTrace",
    "CanonicalTurn",
    "CorpusProfile",
    "DiffReport",
    "Finding",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "audit_traces",
    "diff_audits",
    "iter_traces",
    "load_traces",
    "profile_traces",
]
