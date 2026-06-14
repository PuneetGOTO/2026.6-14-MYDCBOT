"""Process bootstrap helpers."""

from __future__ import annotations


def patch_eventlet() -> None:
    """Apply eventlet monkey patching before runtime imports."""

    import eventlet
    import eventlet.wsgi  # noqa: F401

    eventlet.monkey_patch()
