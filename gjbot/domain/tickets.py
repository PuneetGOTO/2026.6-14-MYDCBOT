"""Ticket domain boundary."""

from __future__ import annotations

from gjbot.subsystems import database_impl as database


def get_ticket_by_id(ticket_id: int):
    return database.db_get_ticket_by_id(ticket_id)


def get_ticket_by_channel(channel_id: int):
    return database.db_get_ticket_by_channel(channel_id)
