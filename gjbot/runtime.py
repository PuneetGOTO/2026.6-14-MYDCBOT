"""Runtime orchestration for the legacy GJBot application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
import threading
from typing import Any

from .app_context import ApplicationContext
from .config import RuntimeSettings


class RuntimeBindingError(RuntimeError):
    """Raised when the legacy module does not expose a required binding."""


@dataclass(frozen=True)
class LegacyRuntime:
    context: Mapping[str, Any]
    settings: RuntimeSettings

    @property
    def application_context(self) -> ApplicationContext:
        class _LegacyModuleView:
            pass

        module_view = _LegacyModuleView()
        for key, value in self.context.items():
            setattr(module_view, key, value)
        return ApplicationContext.from_legacy(module_view)

    def _get_required(self, name: str) -> Any:
        value = self.context.get(name)
        if value is None:
            raise RuntimeBindingError(f"Legacy runtime binding is missing: {name}")
        return value

    def _login_failure_type(self) -> type[BaseException]:
        discord_module = self.context.get("discord")
        if discord_module is None:
            return RuntimeError
        return getattr(getattr(discord_module, "errors", object), "LoginFailure", RuntimeError)

    def _start_alipay_callback_server(self) -> None:
        if not self.context.get("alipay_client"):
            return

        run_http_server = self.context.get("run_http_server")
        if run_http_server is None:
            logging.critical("Alipay client is configured, but run_http_server is missing.")
            return

        alipay_port = self.settings.alipay_callback_port
        http_thread = threading.Thread(
            target=run_http_server,
            args=(alipay_port,),
            daemon=True,
            name="gjbot-alipay-callback",
        )
        http_thread.start()
        print(f"支付宝回调监听器已在后台线程启动，端口: {alipay_port}")

    def _start_web_panel(self) -> None:
        web_app = self.context.get("web_app")
        socketio = self.context.get("socketio")
        run_web_server = self.context.get("run_web_server")

        if web_app and socketio and self.settings.web_panel_configured and run_web_server:
            print("正在检查已注册的路由...")
            print(web_app.url_map)
            web_thread = threading.Thread(
                target=run_web_server,
                daemon=True,
                name="gjbot-web-panel",
            )
            web_thread.start()
            return

        print("⚠️ 警告: Web管理面板配置不完整或Flask/SocketIO不可用，Web服务未启动。")

    def start(self) -> None:
        print("正在启动系统...")
        bot_token = self.context.get("BOT_TOKEN") or self.settings.discord_bot_token
        if not bot_token:
            print("❌ 致命错误：无法启动，因为 DISCORD_BOT_TOKEN 未设置。")
            raise SystemExit(1)

        self._start_alipay_callback_server()
        self._start_web_panel()

        bot = self._get_required("bot")
        login_failure_type = self._login_failure_type()

        try:
            print("正在启动 Discord 机器人...")
            bot.run(bot_token)
        except login_failure_type:
            logging.critical("无法登录机器人：提供了不正确的令牌(DISCORD_BOT_TOKEN)。")
        except KeyboardInterrupt:
            print("\n收到退出信号 (Ctrl+C)，正在关闭机器人...")
        except Exception as exc:
            logging.critical(f"启动机器人时发生致命错误: {exc}", exc_info=True)
        finally:
            print("机器人主循环已结束。程序正在退出。")


def start_legacy_runtime(context: Mapping[str, Any]) -> None:
    """Start the current application through the new runtime boundary."""

    LegacyRuntime(context=context, settings=RuntimeSettings.from_env()).start()
