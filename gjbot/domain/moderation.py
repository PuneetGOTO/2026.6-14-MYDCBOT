"""Moderation domain boundary."""

from __future__ import annotations

from gjbot.subsystems import database_impl as database


def log_action(*args, **kwargs):
    return database.db_log_moderation_action(*args, **kwargs)
