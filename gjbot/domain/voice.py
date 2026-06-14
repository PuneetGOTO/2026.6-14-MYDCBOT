"""Voice channel domain boundary."""

from __future__ import annotations

from gjbot.legacy import require


async def on_voice_state_update(*args, **kwargs):
    return await require("on_voice_state_update")(*args, **kwargs)
