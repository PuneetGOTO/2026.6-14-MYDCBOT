"""Backward-compatible Alipay callback entry point.

The integrated bot runtime uses ``gjbot.subsystems.payments``. This module also
keeps the historical Flask ``app`` available for deployments such as
``gunicorn alipay_callback_handler:app``.
"""

from __future__ import annotations

import os

from gjbot.subsystems.alipay_callback_legacy import app, check_and_process_order

__all__ = ["app", "check_and_process_order", "main", "run_integrated_server"]


def run_integrated_server(port: int | None = None) -> None:
    from gjbot.bootstrap import patch_eventlet
    from gjbot.subsystems.payments import run_http_server

    patch_eventlet()
    run_http_server(port or int(os.environ.get("ALIPAY_CALLBACK_PORT", "8080")))


def main() -> int:
    port = int(os.environ.get("ALIPAY_CALLBACK_PORT", "8080"))
    if os.environ.get("GJBOT_ALIPAY_INTEGRATED") == "1":
        run_integrated_server(port)
    else:
        app.run(host="0.0.0.0", port=port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
