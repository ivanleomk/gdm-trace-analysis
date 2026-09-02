"""Validate traces.jsonl with Harbor ATIF parser.

  uv run --with harbor python validate_atif.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from harbor.utils.trajectory_validator import TrajectoryValidator


def main() -> int:
    path = Path(__file__).resolve().parent / "traces.jsonl"
    v = TrajectoryValidator()
    bad = 0
    n = 0
    with path.open() as f:
        for line in f:
            n += 1
            traj = json.loads(line)
            if not v.validate(traj):
                bad += 1
                print(traj.get("session_id"), v.get_errors(), file=sys.stderr)
    print(f"ok {n - bad}/{n}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
