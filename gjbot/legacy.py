"""Lazy access to the historical monolithic application module."""

from __future__ import annotations

from functools import lru_cache
import importlib
from types import ModuleType
from typing import Any

LEGACY_MODULE_NAME = "gjbot.legacy_app"


@lru_cache(maxsize=1)
def load() -> ModuleType:
    return importlib.import_module(LEGACY_MODULE_NAME)


def context() -> dict[str, Any]:
    return vars(load())


def require(name: str) -> Any:
    module = load()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise RuntimeError(f"Legacy module does not expose {name!r}") from exc
