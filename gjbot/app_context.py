"""Application context objects for gradual legacy extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApplicationContext:
    bot: Any
    database: Any
    web_app: Any | None = None
    socketio: Any | None = None
    alipay_client: Any | None = None

    @classmethod
    def from_legacy(cls, legacy_module: Any) -> "ApplicationContext":
        return cls(
            bot=getattr(legacy_module, "bot"),
            database=getattr(legacy_module, "database"),
            web_app=getattr(legacy_module, "web_app", None),
            socketio=getattr(legacy_module, "socketio", None),
            alipay_client=getattr(legacy_module, "alipay_client", None),
        )
