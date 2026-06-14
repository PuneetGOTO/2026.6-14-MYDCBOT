"""Typed environment access for new GJBot modules.

The legacy module still owns most runtime globals. This module gives new code a
single place to read environment settings while preserving the existing names.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


def _get_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class RuntimeSettings:
    discord_bot_token: str | None
    bot_restart_password: str | None
    deepseek_api_key: str | None
    web_admin_password: str | None
    discord_client_id: str | None
    discord_client_secret: str | None
    discord_redirect_uri: str | None
    alipay_app_id: str | None
    alipay_private_key_path: str | None
    alipay_public_key_for_sdk: str | None
    alipay_public_key_for_verify: str | None
    alipay_notify_url: str | None
    recharge_admin_notification_channel_id: str | None
    recharge_conversion_rate: int
    economy_default_balance: int
    min_recharge_amount: float
    max_recharge_amount: float
    web_port: int
    alipay_callback_port: int

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN"),
            bot_restart_password=os.environ.get("BOT_RESTART_PASSWORD"),
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
            web_admin_password=os.environ.get("WEB_ADMIN_PASSWORD"),
            discord_client_id=os.environ.get("DISCORD_CLIENT_ID"),
            discord_client_secret=os.environ.get("DISCORD_CLIENT_SECRET"),
            discord_redirect_uri=os.environ.get("DISCORD_REDIRECT_URI"),
            alipay_app_id=os.environ.get("ALIPAY_APP_ID"),
            alipay_private_key_path=os.environ.get("ALIPAY_PRIVATE_KEY_PATH"),
            alipay_public_key_for_sdk=os.environ.get("ALIPAY_PUBLIC_KEY_FOR_SDK_CONTENT"),
            alipay_public_key_for_verify=os.environ.get(
                "ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY"
            ),
            alipay_notify_url=os.environ.get("ALIPAY_NOTIFY_URL"),
            recharge_admin_notification_channel_id=os.environ.get(
                "RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID"
            ),
            recharge_conversion_rate=_get_int("RECHARGE_CONVERSION_RATE", 100),
            economy_default_balance=_get_int("ECONOMY_DEFAULT_BALANCE", 100),
            min_recharge_amount=_get_float("MIN_RECHARGE_AMOUNT", 1.0),
            max_recharge_amount=_get_float("MAX_RECHARGE_AMOUNT", 10000.0),
            web_port=_get_int("PORT", 5000),
            alipay_callback_port=_get_int("ALIPAY_CALLBACK_PORT", 8080),
        )

    @property
    def web_panel_configured(self) -> bool:
        return all(
            [
                self.web_admin_password,
                self.discord_client_id,
                self.discord_client_secret,
                self.discord_redirect_uri,
            ]
        )
