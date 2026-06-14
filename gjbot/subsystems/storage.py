"""Storage subsystem adapter."""

from __future__ import annotations

from gjbot.subsystems import database_impl as _database


def __getattr__(name: str):
    return getattr(_database, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_database)))
