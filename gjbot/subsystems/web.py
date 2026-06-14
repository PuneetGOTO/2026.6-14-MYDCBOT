"""Web panel subsystem adapter."""

from __future__ import annotations

from typing import Any

from gjbot.legacy import require


def get_app() -> Any:
    return require("web_app")


def get_socketio() -> Any:
    return require("socketio")


def run_web_server() -> None:
    require("run_web_server")()
