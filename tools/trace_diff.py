#!/usr/bin/env python3
"""CLI wrapper: compare two trace cohorts for regressions and improvements."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trace_review.cli import main_diff

if __name__ == "__main__":
    raise SystemExit(main_diff())
