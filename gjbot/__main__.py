"""Command line entry point for GJBot."""

from __future__ import annotations

import sys


USAGE = """usage: python -m gjbot [--check]

options:
  --check   Run static project checks without importing the Discord bot.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if "-h" in args or "--help" in args:
        print(USAGE)
        return 0

    if args == ["--check"]:
        from .diagnostics import run_check

        return run_check()

    if args:
        print(USAGE)
        return 2

    from .bootstrap import patch_eventlet

    patch_eventlet()

    from .legacy import load
    from .runtime import start_legacy_runtime

    legacy_module = load()
    start_legacy_runtime(vars(legacy_module))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
