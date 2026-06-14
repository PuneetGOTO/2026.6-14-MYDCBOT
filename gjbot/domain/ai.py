"""AI domain boundary."""

from __future__ import annotations

from gjbot.legacy import require


async def check_message_with_deepseek(message_content: str):
    return await require("check_message_with_deepseek")(message_content)
