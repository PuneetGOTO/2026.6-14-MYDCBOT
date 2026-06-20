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
- C# Windows 控制端：獨立 WinForms 控制客戶端與 ASP.NET Core 控制後端，可遠端執行消息、廣播、身份組、成員管理與頻道工具。

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
csharp/                        100% C# Windows 控制客戶端與 ASP.NET Core 控制後端
```

架構說明可參考 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 部署前準備

### 需要準備的帳號與資料

1. Discord Bot Token。
2. Discord OAuth2 Client ID、Client Secret、Redirect URI。
3. Web 面板超級管理員密碼。
4. 一個固定且高強度的 `FLASK_SECRET_KEY`。
5. 可選：DeepSeek API Key。
6. 可選：支付寶 App ID、公鑰、私鑰、回調驗簽公鑰、Notify URL。
7. 生產環境建議準備一個域名，並使用 HTTPS。

### Discord 設定

1. 到 Discord Developer Portal 建立 Application。
2. 在 Bot 頁面建立 Bot，複製 Bot Token。
3. 啟用需要的 Privileged Gateway Intents，例如 Server Members Intent、Message Content Intent。
4. 在 OAuth2 頁面設定 Redirect URI，例如：

```text
https://bot.example.com/callback
```

5. 產生 Bot 邀請連結，至少授予機器人所需的伺服器管理、身份組、頻道、訊息、語音等權限。

### 產生 FLASK_SECRET_KEY

Linux / macOS：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Windows PowerShell：

```powershell
py -c "import secrets; print(secrets.token_hex(32))"
```

把輸出的值填入 `.env` 的 `FLASK_SECRET_KEY`。

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

C# 控制後端可選：

```env
GJBOT_CONTROL_API_KEY=replace-with-a-long-random-control-key
```

`DISCORD_BOT_TOKEN` 仍只放在後端環境中；Windows 控制客戶端只需要後端地址和 `GJBOT_CONTROL_API_KEY`。
Ubuntu 一鍵部署會為 C# 控制後端另建 `csharp-control.env`，只包含 `DISCORD_BOT_TOKEN` 與 `GJBOT_CONTROL_API_KEY`。

## 本地測試

### Windows 本地測試

```powershell
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git
cd 2026.6-14-MYDCBOT
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

建立 `.env` 後執行檢查：

```powershell
python -m gjbot --check
python scripts\smoke_check.py
```

啟動：

```powershell
python -m gjbot
```

如果 PowerShell 不允許啟用虛擬環境，先用系統管理員 PowerShell 執行：

```powershell
Set-ExecutionPolicy RemoteSigned
```

### Linux / macOS 本地測試

```bash
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git
cd 2026.6-14-MYDCBOT
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

建立 `.env` 後執行：

```bash
python -m gjbot --check
python scripts/smoke_check.py
python -m gjbot
```

## Ubuntu / Debian 部署

### 方法一：使用一鍵部署腳本

適用於 Ubuntu 22.04+、Debian 12+，並建議使用乾淨 VPS。

1. 指向域名 DNS A 記錄到伺服器 IP。
2. 登入伺服器。
3. 安裝 Git 與 curl。

```bash
sudo apt update
sudo apt install -y git curl
```

4. 下載專案。

```bash
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git
cd 2026.6-14-MYDCBOT
```

5. 檢查 `get_bot.sh` 裡的設定。

```bash
nano get_bot.sh
```

至少確認：

```bash
GIT_REPO_URL="https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git"
PROJECT_DIR_NAME="GJTEAM-BOT"
BOT_USER="gjteambot"
SERVICE_NAME="gjteam-bot"
```

6. 執行部署。

```bash
chmod +x get_bot.sh
sudo ./get_bot.sh
```

腳本會要求輸入域名、Discord Token、Web 管理密碼、OAuth2 憑證、支付寶資訊等。

腳本也會詢問是否部署 C# 控制後端。如果選擇 `y`，它會在 Ubuntu 上安裝本地 .NET 8 SDK、發布 `csharp/src/GJBot.BotServer`，建立 `gjteam-bot-csharp-api` systemd 服務，並在 Nginx 增加：

```text
https://你的域名/control-api/
```

Windows 控制客戶端的「後端地址」就填這個 URL，API Key 填部署時輸入的 `GJBOT_CONTROL_API_KEY`。

7. 查看服務狀態。

```bash
sudo systemctl status gjteam-bot
sudo journalctl -u gjteam-bot -f
```

8. 常用管理命令。

```bash
sudo systemctl restart gjteam-bot
sudo systemctl stop gjteam-bot
sudo systemctl start gjteam-bot
```

注意：如果 certbot 申請 HTTPS 失敗，腳本會停止，不會讓 Web 面板用 HTTP 明文繼續運行。

### 方法二：Ubuntu / Debian 手動部署

1. 安裝系統依賴。

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv nginx ffmpeg build-essential certbot python3-certbot-nginx
```

2. 建立專用使用者。

```bash
sudo useradd -r -m -d /home/gjteambot -s /bin/bash gjteambot
sudo su - gjteambot
```

3. 下載專案與安裝依賴。

```bash
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git GJTEAM-BOT
cd GJTEAM-BOT
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

4. 建立 `.env`。

```bash
nano .env
```

填入前面「環境變量」章節的內容。

5. 回到 root 或 sudo 使用者，建立 systemd 服務。

```bash
exit
sudo nano /etc/systemd/system/gjteam-bot.service
```

貼上：

```ini
[Unit]
Description=GJBot Discord Bot and Web Panel
After=network.target

[Service]
User=gjteambot
Group=gjteambot
WorkingDirectory=/home/gjteambot/GJTEAM-BOT
ExecStart=/home/gjteambot/GJTEAM-BOT/venv/bin/python -m gjbot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

6. 啟動服務。

```bash
sudo systemctl daemon-reload
sudo systemctl enable gjteam-bot
sudo systemctl start gjteam-bot
sudo journalctl -u gjteam-bot -f
```

7. 設定 Nginx。

```bash
sudo nano /etc/nginx/sites-available/gjbot
```

範例：

```nginx
server {
    listen 80;
    server_name bot.example.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /my-custom-socket-path {
        proxy_pass http://127.0.0.1:5000/my-custom-socket-path;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /alipay/notify {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /home/gjteambot/GJTEAM-BOT/static/;
        expires 1d;
        add_header Cache-Control "public";
    }
}
```

啟用：

```bash
sudo ln -s /etc/nginx/sites-available/gjbot /etc/nginx/sites-enabled/gjbot
sudo nginx -t
sudo systemctl reload nginx
```

8. 申請 HTTPS。

```bash
sudo certbot --nginx -d bot.example.com
```

9. 更新 `.env` 中的 URL 為 HTTPS。

```env
DISCORD_REDIRECT_URI=https://bot.example.com/callback
ALIPAY_NOTIFY_URL=https://bot.example.com/alipay/notify
```

更新後重啟：

```bash
sudo systemctl restart gjteam-bot
```

### Ubuntu / Debian 可選 C# 控制後端手動部署

如果你不用一鍵腳本，也可以在同一台 Ubuntu / Debian VPS 上手動部署 C# 控制後端，供 Windows 控制客戶端遠端連線。

1. 安裝 .NET 8 到專案本地目錄。

```bash
sudo su - gjteambot
cd /home/gjteambot/GJTEAM-BOT
curl -fsSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
bash dotnet-install.sh --channel 8.0 --install-dir /home/gjteambot/GJTEAM-BOT/.dotnet
```

2. 發布 C# 後端。

```bash
/home/gjteambot/GJTEAM-BOT/.dotnet/dotnet publish \
  /home/gjteambot/GJTEAM-BOT/csharp/src/GJBot.BotServer/GJBot.BotServer.csproj \
  -c Release \
  -o /home/gjteambot/GJTEAM-BOT/csharp-control-server \
  --self-contained false
exit
```

3. 建立 C# 控制後端專用環境檔。

```bash
sudo nano /home/gjteambot/GJTEAM-BOT/csharp-control.env
```

填入：

```env
DISCORD_BOT_TOKEN=replace-me
GJBOT_CONTROL_API_KEY=replace-with-a-long-random-control-key
```

設定權限：

```bash
sudo chown gjteambot:gjteambot /home/gjteambot/GJTEAM-BOT/csharp-control.env
sudo chmod 600 /home/gjteambot/GJTEAM-BOT/csharp-control.env
```

4. 建立 systemd 服務。

```bash
sudo nano /etc/systemd/system/gjteam-bot-csharp-api.service
```

貼上：

```ini
[Unit]
Description=GJBot C# Control API
After=network.target

[Service]
User=gjteambot
Group=gjteambot
WorkingDirectory=/home/gjteambot/GJTEAM-BOT
EnvironmentFile=/home/gjteambot/GJTEAM-BOT/csharp-control.env
ExecStart=/home/gjteambot/GJTEAM-BOT/.dotnet/dotnet /home/gjteambot/GJTEAM-BOT/csharp-control-server/GJBot.BotServer.dll --urls http://127.0.0.1:5088
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

啟動：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gjteam-bot-csharp-api
sudo journalctl -u gjteam-bot-csharp-api -f
```

5. 在 Nginx 站點中加入 C# 控制 API 反向代理。

```nginx
location = /control-api {
    return 301 /control-api/;
}

location /control-api/ {
    proxy_pass http://127.0.0.1:5088/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

套用：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Windows 控制客戶端的後端地址填：

```text
https://bot.example.com/control-api/
```

## RHEL / Rocky Linux / AlmaLinux / CentOS 部署

以下命令以 Rocky Linux 9 / AlmaLinux 9 為例。

1. 安裝依賴。

```bash
sudo dnf update -y
sudo dnf install -y git python3 python3-pip nginx ffmpeg gcc gcc-c++ make certbot python3-certbot-nginx
```

如果系統沒有 `ffmpeg`，可能需要啟用 EPEL / RPM Fusion：

```bash
sudo dnf install -y epel-release
```

2. 建立使用者與下載專案。

```bash
sudo useradd -r -m -d /home/gjteambot -s /bin/bash gjteambot
sudo su - gjteambot
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git GJTEAM-BOT
cd GJTEAM-BOT
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3. 建立 `.env`。

```bash
nano .env
```

4. 建立 systemd 服務。

```bash
exit
sudo nano /etc/systemd/system/gjteam-bot.service
```

內容同 Ubuntu 手動部署的 systemd 範例。

5. 啟動服務。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gjteam-bot
sudo journalctl -u gjteam-bot -f
```

6. 設定防火牆。

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

7. 設定 Nginx。

RHEL 系通常可放在：

```bash
sudo nano /etc/nginx/conf.d/gjbot.conf
```

內容可使用 Ubuntu Nginx 範例。

測試並重載：

```bash
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

8. 申請 HTTPS。

```bash
sudo certbot --nginx -d bot.example.com
```

## Windows 部署

Windows 適合測試或內部使用。生產環境仍建議用 Linux + Nginx + HTTPS。

### 方法一：PowerShell 前台運行

```powershell
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git
cd 2026.6-14-MYDCBOT
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m gjbot --check
python scripts\smoke_check.py
python -m gjbot
```

### 方法二：使用 NSSM 設成 Windows 服務

1. 下載 NSSM：https://nssm.cc/download
2. 解壓後把 `nssm.exe` 放到固定位置，例如 `C:\nssm\nssm.exe`。
3. 先完成專案下載、虛擬環境與 `.env` 設定。
4. 使用系統管理員 PowerShell：

```powershell
C:\nssm\nssm.exe install GJBot
```

NSSM 視窗設定：

```text
Application path: C:\Path\To\2026.6-14-MYDCBOT\venv\Scripts\python.exe
Startup directory: C:\Path\To\2026.6-14-MYDCBOT
Arguments: -m gjbot
```

5. 啟動服務：

```powershell
C:\nssm\nssm.exe start GJBot
```

6. 停止或重啟：

```powershell
C:\nssm\nssm.exe stop GJBot
C:\nssm\nssm.exe restart GJBot
```

### Windows 反向代理

如果要公開 Web 面板，建議使用 Caddy 或 Nginx for Windows 做 HTTPS 反向代理。

### Windows C# 控制客戶端

C# 控制端位於 `csharp/`。它分成兩部分：

- `GJBot.BotServer`：ASP.NET Core 控制後端，保存 Discord Bot Token 並呼叫 Discord API。
- `GJBot.ControlClient`：WinForms Windows 控制客戶端，只保存後端地址與控制 API Key。

如果後端部署在本機：

```powershell
$env:DISCORD_BOT_TOKEN="你的 Discord Bot Token"
$env:GJBOT_CONTROL_API_KEY="你的控制 API Key"
dotnet run --project E:\GJBOT\csharp\src\GJBot.BotServer --urls "http://localhost:5088"
dotnet run --project E:\GJBOT\csharp\src\GJBot.ControlClient
```

如果後端已用 Ubuntu 部署到 VPS，Windows 客戶端填：

```text
後端地址：https://你的域名/control-api/
API Key：Ubuntu 部署時填入的 GJBOT_CONTROL_API_KEY
```

更多 C# 使用方式見 `csharp/README.md`。

Caddyfile 範例：

```caddyfile
bot.example.com {
    reverse_proxy 127.0.0.1:5000

    handle_path /alipay/notify {
        reverse_proxy 127.0.0.1:8080
    }
}
```

注意：Socket.IO path 是 `/my-custom-socket-path`，反向代理必須支援 WebSocket。

## macOS 部署

macOS 適合測試或小型常駐，不建議作為公開生產環境。

1. 安裝 Homebrew。
2. 安裝依賴。

```bash
brew install python git ffmpeg
```

3. 下載並安裝 Python 依賴。

```bash
git clone https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git
cd 2026.6-14-MYDCBOT
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

4. 建立 `.env` 並測試。

```bash
python -m gjbot --check
python scripts/smoke_check.py
python -m gjbot
```

5. 如果要常駐，可建立 launchd plist。

```bash
mkdir -p ~/Library/LaunchAgents
nano ~/Library/LaunchAgents/com.gjbot.plist
```

範例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gjbot</string>
    <key>WorkingDirectory</key>
    <string>/absolute/path/to/2026.6-14-MYDCBOT</string>
    <key>ProgramArguments</key>
    <array>
        <string>/absolute/path/to/2026.6-14-MYDCBOT/venv/bin/python</string>
        <string>-m</string>
        <string>gjbot</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

啟用：

```bash
launchctl load ~/Library/LaunchAgents/com.gjbot.plist
launchctl start com.gjbot
```

## 雲平台部署注意事項

### Railway / Render / Fly.io / 其他 PaaS

此專案可以在支援 Python 的平台上運行，但要注意：

- 啟動命令使用：

```bash
python -m gjbot
```

- 必須在平台環境變量中設定 `.env` 內容。
- Web 面板使用 `PORT`，平台通常會自動提供。
- 支付寶回調如果需要獨立 8080 端口，某些 PaaS 不支援多端口。這種情況建議改為同一個 Flask app 路由，或使用 VPS。
- SQLite 在部分 PaaS 上可能不是持久化儲存。若平台檔案系統會重置，經濟資料、票據資料與充值資料會遺失。
- 生產部署建議使用有持久磁碟的 VPS，或後續改成 PostgreSQL。

### Docker

目前專案沒有內建 Dockerfile。若要自行 Docker 化，基本方向是：

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y ffmpeg build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "gjbot"]
```

Docker 部署時請用環境變量或 secret manager 注入 `.env`，不要把 `.env` COPY 進映像。

## Nginx 與 HTTPS 檢查清單

- `DISCORD_REDIRECT_URI` 必須和 Discord Developer Portal 完全一致。
- `ALIPAY_NOTIFY_URL` 必須是可被支付寶訪問的 HTTPS URL。
- Nginx 要轉發 `X-Forwarded-Proto`，專案已使用 `ProxyFix`。
- Socket.IO 需要 WebSocket Upgrade header。
- Web 面板不要直接暴露 HTTP。
- 憑證更新可用：

```bash
sudo certbot renew --dry-run
```

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

## 常見問題

### Web 面板沒有啟動

檢查：

- `FLASK_SECRET_KEY`
- `WEB_ADMIN_PASSWORD`
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_REDIRECT_URI`
- Web port 是否被佔用

### Discord OAuth 登入失敗

確認 Discord Developer Portal 裡設定的 Redirect URI 與 `.env` 的 `DISCORD_REDIRECT_URI` 完全一致，包括 `https`、域名、路徑與尾斜線。

### 支付寶回調驗證失敗

檢查：

- `ALIPAY_APP_ID`
- `ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY`
- `ALIPAY_NOTIFY_URL`
- 沙箱與正式環境公鑰是否混用

### 音樂功能無法播放

檢查：

- `ffmpeg` 是否已安裝
- Lavalink / wavelink 相關配置是否完整
- Discord Bot 是否有語音頻道連線與發言權限

### 資料重啟後遺失

確認目前部署環境是否有持久化磁碟。SQLite 資料庫檔不要放在會被平台重置的臨時目錄。
