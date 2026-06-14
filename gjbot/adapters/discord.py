"""Discord adapter helpers."""

from __future__ import annotations

from typing import Any


def get_bot_from_context(context: Any) -> Any:
    return context.bot
