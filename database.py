"""Backward-compatible database module alias."""

from __future__ import annotations

import sys

from gjbot.subsystems import database_impl as _database_impl

sys.modules[__name__] = _database_impl
