"""Economy domain boundary."""

from __future__ import annotations

from gjbot.subsystems import database_impl as database


def get_user_balance(guild_id: int, user_id: int, default_balance: int) -> int:
    return database.db_get_user_balance(guild_id, user_id, default_balance)


def apply_balance_delta(guild_id: int, user_id: int, delta: int, default_balance: int = 0) -> bool:
    return database.db_apply_user_balance_delta(guild_id, user_id, delta, default_balance)


def set_user_balance(guild_id: int, user_id: int, balance: int) -> bool:
    return database.db_set_user_balance(guild_id, user_id, balance)
