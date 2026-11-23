"""Allow `python3 -m trace_review <command>`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
