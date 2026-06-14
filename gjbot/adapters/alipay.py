"""Alipay adapter helpers."""

from __future__ import annotations

from typing import Any


def get_alipay_client_from_context(context: Any) -> Any:
    return context.alipay_client
