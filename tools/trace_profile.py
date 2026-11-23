#!/usr/bin/env python3
"""CLI wrapper: profile traces across any format without reading full transcripts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trace_review.cli import main_profile

if __name__ == "__main__":
    raise SystemExit(main_profile())
