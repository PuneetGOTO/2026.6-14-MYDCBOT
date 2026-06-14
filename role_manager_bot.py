"""Backward-compatible launcher for the legacy GJBot application.

The monolithic implementation has moved to ``gjbot.legacy_app``. Running this
file still starts the full bot, Web panel, and payment callback stack.
"""

from __future__ import annotations


def __getattr__(name: str):
    from gjbot.legacy import require

    return require(name)


def __dir__() -> list[str]:
    from gjbot.legacy import load

    return sorted(set(globals()) | set(dir(load())))


def main() -> int:
    from gjbot.bootstrap import patch_eventlet

    patch_eventlet()

    from gjbot.legacy import load
    from gjbot.runtime import start_legacy_runtime

    legacy_module = load()
    start_legacy_runtime(vars(legacy_module))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
