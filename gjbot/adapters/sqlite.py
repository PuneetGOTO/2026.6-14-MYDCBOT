"""SQLite adapter helpers."""

from __future__ import annotations

from gjbot.subsystems import database_impl


def get_database_module():
    return database_impl
