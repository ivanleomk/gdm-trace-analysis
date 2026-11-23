#!/usr/bin/env python3
"""CLI wrapper: audit traces with universal detectors, JSON schema, and declarative policy rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trace_review.cli import main_audit

if __name__ == "__main__":
    raise SystemExit(main_audit())
