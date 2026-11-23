#!/usr/bin/env python3
"""CLI wrapper: slice, stratified-sample, and inspect matching trace sessions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trace_review.cli import main_inspect

if __name__ == "__main__":
    raise SystemExit(main_inspect())
