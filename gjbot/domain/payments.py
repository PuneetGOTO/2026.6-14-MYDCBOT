"""Payment domain boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gjbot.subsystems.payments import process_successful_payment


async def handle_successful_payment(params: Mapping[str, Any]) -> None:
    await process_successful_payment(params)
