"""Static diagnostics for the refactored project layout."""

from __future__ import annotations

from pathlib import Path
import py_compile


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "role_manager_bot.py",
    "database.py",
    "music_cog.py",
    "alipay_callback_handler.py",
    "requirements.txt",
    "templates",
    "static",
    "gjbot",
]

PYTHON_FILES = [
    "role_manager_bot.py",
    "database.py",
    "music_cog.py",
    "alipay_callback_handler.py",
    "gjbot/__init__.py",
    "gjbot/__main__.py",
    "gjbot/config.py",
    "gjbot/bootstrap.py",
    "gjbot/app_context.py",
    "gjbot/runtime.py",
    "gjbot/legacy.py",
    "gjbot/legacy_app.py",
    "gjbot/diagnostics.py",
    "gjbot/subsystems/__init__.py",
    "gjbot/subsystems/bot.py",
    "gjbot/subsystems/payments.py",
    "gjbot/subsystems/storage.py",
    "gjbot/subsystems/web.py",
    "gjbot/subsystems/database_impl.py",
    "gjbot/subsystems/music_cog_impl.py",
    "gjbot/subsystems/alipay_callback_legacy.py",
    "gjbot/adapters/__init__.py",
    "gjbot/adapters/discord.py",
    "gjbot/adapters/flask.py",
    "gjbot/adapters/sqlite.py",
    "gjbot/adapters/alipay.py",
    "gjbot/domain/__init__.py",
    "gjbot/domain/ai.py",
    "gjbot/domain/economy.py",
    "gjbot/domain/moderation.py",
    "gjbot/domain/tickets.py",
    "gjbot/domain/voice.py",
    "gjbot/domain/music.py",
    "gjbot/domain/payments.py",
    "scripts/smoke_check.py",
]


def run_check() -> int:
    failed = False

    for relative_path in REQUIRED_PATHS:
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            print(f"[missing] {relative_path}")
            failed = True
        else:
            print(f"[ok] {relative_path}")

    for relative_path in PYTHON_FILES:
        path = PROJECT_ROOT / relative_path
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            print(f"[compile-error] {relative_path}: {exc}")
            failed = True
        else:
            print(f"[compile-ok] {relative_path}")

    return 1 if failed else 0
