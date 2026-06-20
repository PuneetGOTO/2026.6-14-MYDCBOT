"""Project smoke checks that do not require Discord network access."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database
from gjbot.subsystems import database_impl


def check_database_alias() -> None:
    assert database is database_impl
    assert hasattr(database, "initialize_database")
    assert hasattr(database, "db_update_recharge_request_status")


def check_database_transactions() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        database.DATABASE_FILE = path
        database.initialize_database()
        assert database.db_get_user_balance(1, 2, 100) == 100
        assert database.db_apply_user_balance_delta(1, 2, 50, default_balance=100)
        assert database.db_get_user_balance(1, 2, 0) == 150
        assert not database.db_apply_user_balance_delta(1, 2, -200, default_balance=100)
        assert database.db_get_user_balance(1, 2, 0) == 150
        assert database.db_set_user_balance(1, 2, 12)
        assert database.db_get_user_balance(1, 2, 0) == 12
        huge_balance = 10**80
        assert database.db_set_user_balance(1, 2, huge_balance)
        assert database.db_get_user_balance(1, 2, 0) == huge_balance
        assert database.db_apply_user_balance_delta(1, 2, 10**70, default_balance=100)
        assert database.db_get_user_balance(1, 2, 0) == huge_balance + 10**70
        assert database.db_apply_user_balance_delta(1, 3, 10**75, default_balance=100)
        leaderboard = database.db_get_leaderboard(1, 10)
        assert leaderboard[0][0] == 2
        stats = database.db_get_economy_stats(1)
        expected_total = huge_balance + 10**70 + 100 + 10**75
        assert stats["total_currency"] == str(expected_total)
        assert stats["total_currency_display"] == str(expected_total)
        assert stats["top_users"][0]["balance_display"] == str(huge_balance + 10**70)

        ok, _ = database.db_add_shop_item(1, "item", "Item", 10, "", None, 1, None)
        assert ok
        assert database.db_decrement_shop_item_stock(1, "item")
        assert database.db_get_shop_item(1, "item")["stock"] == 0
        assert not database.db_decrement_shop_item_stock(1, "item")

        request_id = database.db_create_initial_recharge_request(1, 2, 3.0, "trade-test")
        assert request_id
        assert database.db_update_recharge_request_status(
            request_id,
            "AMOUNT_ISSUE",
            "bad amount",
        )
        request = database.db_get_recharge_request_by_out_trade_no("trade-test")
        assert request["status"] == "AMOUNT_ISSUE"

        completed_request_id = database.db_create_initial_recharge_request(1, 2, 4.0, "trade-complete")
        assert completed_request_id
        assert database.db_complete_recharge_and_credit_balance(
            completed_request_id,
            "alipay-trade-complete",
            4.0,
            1,
            2,
            400,
            default_balance=100,
        )
        completed_request = database.db_get_recharge_request_by_out_trade_no("trade-complete")
        assert completed_request["status"] == "COMPLETED"
        assert database.db_get_user_balance(1, 2, 0) == huge_balance + 10**70 + 400

        access_key = database.db_create_sub_account(
            "smoke-sub-account",
            {"can_manage_all_guilds": True, "guilds": []},
        )
        assert access_key
        conn = database.get_db_connection()
        try:
            stored_key = conn.execute(
                f"SELECT access_key FROM {database.TABLE_WEB_SUB_ACCOUNTS} WHERE account_name = ?",
                ("smoke-sub-account",),
            ).fetchone()["access_key"]
        finally:
            conn.close()
        assert stored_key != access_key
        assert stored_key.startswith("pbkdf2_sha256$")
        assert database.db_validate_access_key(access_key)["account_name"] == "smoke-sub-account"

        conn = database.get_db_connection()
        try:
            conn.execute(
                f"INSERT INTO {database.TABLE_WEB_SUB_ACCOUNTS} (account_name, access_key, permissions_json, created_at) VALUES (?, ?, ?, ?)",
                ("legacy-sub-account", "legacy-key", '{"guilds": []}', 1),
            )
            conn.commit()
        finally:
            conn.close()
        assert database.db_validate_access_key("legacy-key")["account_name"] == "legacy-sub-account"
        conn = database.get_db_connection()
        try:
            upgraded_key = conn.execute(
                f"SELECT access_key FROM {database.TABLE_WEB_SUB_ACCOUNTS} WHERE account_name = ?",
                ("legacy-sub-account",),
            ).fetchone()["access_key"]
        finally:
            conn.close()
        assert upgraded_key.startswith("pbkdf2_sha256$")
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def check_compat_modules() -> None:
    import alipay_callback_handler
    import music_cog

    assert alipay_callback_handler.app is not None
    assert hasattr(alipay_callback_handler, "check_and_process_order")
    assert hasattr(music_cog, "setup")


def main() -> int:
    check_database_alias()
    check_database_transactions()
    check_compat_modules()
    print("smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
