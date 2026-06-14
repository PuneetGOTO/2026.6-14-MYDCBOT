"""Flask adapter helpers."""

from __future__ import annotations

from typing import Any


def get_web_app_from_context(context: Any) -> Any:
    return context.web_app


def get_socketio_from_context(context: Any) -> Any:
    return context.socketio
