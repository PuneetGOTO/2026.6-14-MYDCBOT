# GJBot

GJBot 是一套 Discord 社群管理機器人，內建 Flask Web 管理面板。它把伺服器管理、身份組管理、內容審核、票據客服、音樂控制、經濟系統、AI 輔助流程，以及支付寶充值回調整合在同一個運行環境中。

目前專案保留舊版單體程式的兼容入口，同時提供新的套件入口：

```bash
python -m gjbot
```

## 主要功能

- Discord 斜線指令：身份組、管理、票據、語音、經濟系統等工作流。
- Web 管理面板：Discord OAuth 登入、超級管理員登入、副帳號登入、伺服器管理、票據管理、審核工具、音樂控制、備份還原、全域廣播。
- 票據系統：部門設定、客服分配、聊天記錄歸檔、AI 回覆建議、Web 面板直接回覆 Discord。
- 經濟與商店系統：餘額管理、庫存安全扣減、充值記錄、排行榜和統計 API。
- 支付寶充值：預下單、簽名回調驗證、訂單金額核對、交易號防重複、原子化上分。
- AI 功能：內容審核、知識庫、FAQ 和 AI 對話頻道。

## 專案結構

```text
gjbot/                         套件入口、運行邊界與兼容層
gjbot/legacy_app.py            主要舊版單體程式，包含 Bot、Web 面板和支付邏輯
gjbot/subsystems/              已抽出的子系統實作與適配器
templates/                     Flask / Jinja Web 面板模板
static/                        Web 面板 CSS 與 JavaScript
scripts/smoke_check.py         本地 smoke test
role_manager_bot.py            舊入口兼容啟動器
alipay_callback_handler.py     支付寶回調兼容入口
```

架構說明可參考 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 環境需求

- Python 3.10 或更新版本
- Discord Bot Application 與 Bot Token
- Discord OAuth2 Application，用於 Web 面板登入
- 可選：支付寶沙箱或正式應用憑證
- 可選：DeepSeek 兼容 API Key，用於 AI 功能
- 生產部署建議：Nginx、certbot、systemd、ffmpeg

安裝 Python 依賴：

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Linux 或 macOS 啟用虛擬環境：

```bash
source venv/bin/activate
```

## 環境變量

請建立本地 `.env`，或在部署平台設定同名環境變量。不要把真實密鑰提交到 Git。

Discord Bot 必填：

```env
DISCORD_BOT_TOKEN=replace-me
```

Web 面板必填：

```env
FLASK_SECRET_KEY=replace-with-64-plus-random-hex-chars
WEB_ADMIN_PASSWORD=replace-me
DISCORD_CLIENT_ID=replace-me
DISCORD_CLIENT_SECRET=replace-me
DISCORD_REDIRECT_URI=https://your-domain.example/callback
```

AI 功能可選：

```env
DEEPSEEK_API_KEY=replace-me
```

支付寶充值可選：

```env
ALIPAY_APP_ID=replace-me
ALIPAY_PRIVATE_KEY_PATH=/absolute/path/to/alipay_private_key.pem
ALIPAY_PUBLIC_KEY_FOR_SDK_CONTENT=replace-me
ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY=replace-me
ALIPAY_NOTIFY_URL=https://your-domain.example/alipay/notify
RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID=123456789012345678
RECHARGE_CONVERSION_RATE=100
MIN_RECHARGE_AMOUNT=1.0
MAX_RECHARGE_AMOUNT=10000.0
```

常用運行配置：

```env
PORT=5000
ALIPAY_CALLBACK_PORT=8080
ECONOMY_DEFAULT_BALANCE=100
```

## 本地運行

先執行靜態檢查與 smoke test：

```bash
python -m gjbot --check
python scripts/smoke_check.py
```

啟動完整運行環境：

```bash
python -m gjbot
```

運行時會啟動 Discord Bot。如果 Web 面板配置完整，會同時啟動 Web 面板；如果支付寶配置完整，會同時啟動支付寶回調監聽器。

## 部署

`get_bot.sh` 是面向 Ubuntu 的一鍵部署腳本，會建立專用系統使用者、Python 虛擬環境、Nginx 反向代理、certbot TLS 憑證，以及 systemd 服務。

部署前請檢查 `get_bot.sh` 內的：

```bash
GIT_REPO_URL
PROJECT_DIR_NAME
BOT_USER
SERVICE_NAME
```

重要部署行為：

- 腳本會自動生成 `FLASK_SECRET_KEY`。
- 如果 TLS 憑證申請失敗，腳本會停止，不會讓 Web 面板、OAuth 回調或支付回調以 HTTP 明文方式繼續運行。
- `.env`、支付寶私鑰、資料庫、聊天記錄、日誌、Python 快取都已被 `.gitignore` 排除。

## 安全設計

- 禁止提交 `.env`、私鑰、資料庫、聊天記錄和日誌。
- Web 面板必須設定 `FLASK_SECRET_KEY`，否則不會啟動。
- 超級管理員登入與副帳號登入有基本的進程內限速。
- 副帳號 access key 使用 PBKDF2 雜湊儲存；舊版明文 key 在成功登入後會自動升級。
- Web 高風險操作會檢查伺服器範圍內的權限。
- 支付寶回調會驗證簽名、`app_id`、訂單狀態、交易號重複和支付金額。
- 充值完成與餘額上分在同一個 SQLite 交易中完成，避免部分成功的中間狀態。
- 票據 transcript 頁面加上 CSP，並對附件 URL 和頭像 URL 做 HTML escape。

## 驗證命令

部署或提交前建議執行：

```bash
python -m gjbot --check
python scripts/smoke_check.py
python -m py_compile role_manager_bot.py database.py music_cog.py alipay_callback_handler.py
```

`scripts/smoke_check.py` 使用臨時資料庫，不需要 Discord 網路連線。

## 常見注意事項

- 如果 Web 面板沒有啟動，先確認 `FLASK_SECRET_KEY`、`WEB_ADMIN_PASSWORD`、`DISCORD_CLIENT_ID`、`DISCORD_CLIENT_SECRET`、`DISCORD_REDIRECT_URI` 是否完整。
- 如果支付寶回調驗證失敗，檢查 `ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY` 與支付寶應用是否匹配。
- 如果 Discord OAuth 登入失敗，確認 Discord Developer Portal 裡設定的 Redirect URI 與 `DISCORD_REDIRECT_URI` 完全一致。
- 生產環境應只使用 HTTPS，不建議暴露 HTTP 管理面板。

