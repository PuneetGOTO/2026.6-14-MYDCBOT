"""Payment subsystem adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gjbot.legacy import require


def get_alipay_client() -> Any:
    return require("alipay_client")


def run_http_server(port: int = 8080) -> None:
    require("run_http_server")(port)


async def process_successful_payment(params: Mapping[str, Any]) -> None:
    await require("process_successful_payment")(dict(params))
