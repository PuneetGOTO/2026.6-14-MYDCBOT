# GJBot

GJBot is a Discord community management bot with a Flask-based Web control
panel. It combines moderation tools, ticket support, music controls, economy
features, AI-assisted workflows, and Alipay recharge handling in one runtime.

The current codebase keeps the historical monolithic implementation available
through compatibility entry points while exposing a package entry point at
`python -m gjbot`.

## Features

- Discord slash-command bot for role, moderation, ticket, voice, and economy
  workflows.
- Web dashboard with Discord OAuth login, superuser login, sub-account access,
  guild management pages, ticket views, audit tools, music controls, backup and
  restore pages, and global broadcast tools.
- Ticket system with departments, staff assignment, transcripts, AI reply
  suggestions, and Web-to-Discord replies.
- Economy and shop system with balance updates, stock-safe purchases, recharge
  records, and leaderboard/stat APIs.
- Alipay pre-create recharge flow with signed callback verification and
  transaction-safe balance crediting.
- AI moderation and knowledge-base features using an external API key.

## Project Layout

```text
gjbot/                         Package runtime and compatibility boundaries
gjbot/legacy_app.py            Main legacy bot, Web panel, and payment logic
gjbot/subsystems/              Extracted subsystem adapters and implementations
templates/                     Flask/Jinja Web panel templates
static/                        Web panel CSS and JavaScript
scripts/smoke_check.py         Local verification checks
role_manager_bot.py            Backward-compatible launcher
alipay_callback_handler.py     Backward-compatible Alipay callback entry point
```

More architecture notes are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- Python 3.10 or newer
- Discord bot application and token
- Discord OAuth2 application for the Web panel
- Optional: Alipay sandbox or production application credentials
- Optional: DeepSeek-compatible API key for AI features
- Optional production stack: Nginx, certbot, systemd, ffmpeg

Install Python dependencies:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

On Linux/macOS, activate with `source venv/bin/activate`.

## Configuration

Create a local `.env` file or set equivalent environment variables. Do not
commit real secrets.

Required for the Discord bot:

```env
DISCORD_BOT_TOKEN=replace-me
```

Required for the Web panel:

```env
FLASK_SECRET_KEY=replace-with-64-plus-random-hex-chars
WEB_ADMIN_PASSWORD=replace-me
DISCORD_CLIENT_ID=replace-me
DISCORD_CLIENT_SECRET=replace-me
DISCORD_REDIRECT_URI=https://your-domain.example/callback
```

Optional AI configuration:

```env
DEEPSEEK_API_KEY=replace-me
```

Optional Alipay recharge configuration:

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

Runtime defaults:

```env
PORT=5000
ALIPAY_CALLBACK_PORT=8080
ECONOMY_DEFAULT_BALANCE=100
```

## Running Locally

Run static project checks:

```bash
python -m gjbot --check
python scripts/smoke_check.py
```

Start the integrated runtime:

```bash
python -m gjbot
```

The runtime starts the Discord bot, the Web panel if fully configured, and the
Alipay callback listener if Alipay is configured.

## Deployment

`get_bot.sh` is an Ubuntu-oriented installer for a dedicated system user,
Python virtual environment, Nginx reverse proxy, certbot TLS certificate, and
systemd service.

Important deployment behavior:

- The installer generates `FLASK_SECRET_KEY` automatically.
- The installer stops if TLS certificate setup fails, so the Web panel, OAuth
  callback, and payment callback are not left running over plain HTTP.
- Generated `.env`, Alipay private keys, database files, transcripts, logs, and
  Python cache files are intentionally excluded by `.gitignore`.

Review `GIT_REPO_URL` in `get_bot.sh` before running it on a server.

## Security Notes

- Never commit `.env`, private keys, database files, transcripts, or logs.
- `FLASK_SECRET_KEY` is mandatory for the Web panel.
- Web login endpoints include basic in-process rate limiting.
- Sub-account access keys are stored as PBKDF2 hashes; legacy plaintext keys
  are upgraded after a successful login.
- Sensitive Web actions require server-scoped permission checks.
- Payment callbacks verify Alipay signatures, app IDs, order state, duplicate
  trade numbers, and paid amounts before crediting balances.
- Payment completion and balance crediting happen in a single SQLite
  transaction.

## Verification

Before deploying changes, run:

```bash
python -m gjbot --check
python scripts/smoke_check.py
python -m py_compile role_manager_bot.py database.py music_cog.py alipay_callback_handler.py
```

The smoke check uses a temporary database and does not require Discord network
access.

