"""Discord bot subsystem adapter."""

from __future__ import annotations

from typing import Any

from gjbot.legacy import require
from gjbot.runtime import start_legacy_runtime


def get_bot() -> Any:
    return require("bot")


def get_command_tree() -> Any:
    return get_bot().tree


def run() -> None:
    from gjbot.legacy import context

    start_legacy_runtime(context())
