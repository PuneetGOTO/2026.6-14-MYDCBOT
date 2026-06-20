# GJBot 架構說明

本專案目前保留舊版單體機器人程式，同時新增套件化入口與 C# 控制端。這樣可以讓既有 Web 面板、Bot 指令、支付邏輯繼續運行，也方便之後逐步把功能拆成更清楚的模組。

## 運行邊界

- `python -m gjbot` 是新的 Python 套件入口。
- `gjbot.legacy_app` 保存原本的單體實作，包含 Discord Bot、Flask Web 面板、Socket.IO、資料庫與支付流程。
- `role_manager_bot.py` 仍然可以直接執行，用於舊部署兼容；實際啟動流程會交給 `gjbot.runtime`。
- `gjbot.runtime` 負責整個 Python 服務的啟動流程，包括支付寶回調服務、Web 面板執行緒與 Discord Bot 啟動。
- `gjbot.legacy` 是延遲載入橋接層，用來把新模組安全接到既有單體程式。
- `csharp/` 是可選的純 C# 控制層，由 ASP.NET Core 控制後端與 WinForms Windows 客戶端組成，透過 Discord REST API v10 執行管理操作。它不接管 Python Bot 運行環境、Flask 登入 Session、Socket.IO 狀態或 SQLite 業務資料。

## 子系統適配層

- `gjbot.app_context.ApplicationContext` 是抽出服務時使用的型別化依賴邊界。
- `gjbot.adapters.*` 放外部系統適配工具。
- `gjbot.domain.*` 放業務邊界，例如經濟、票據、審核、AI、語音、音樂與支付。
- `gjbot.subsystems.bot` 對外提供 Discord Bot 物件與指令樹。
- `gjbot.subsystems.web` 對外提供 Flask app、Socket.IO 物件與 Web 服務啟動器。
- `gjbot.subsystems.payments` 對外提供支付寶客戶端、回調服務與支付成功處理器。
- `alipay_callback_handler.py` 保留為兼容啟動器，不再擁有獨立支付實作。
- `gjbot.subsystems.alipay_callback_legacy` 保存之前獨立回調程式的參考版本，方便遷移期間對照。
- `gjbot.subsystems.music_cog_impl` 放 Discord 音樂 Cog 實作。
- `music_cog.py` 保留為舊 import 的兼容模組。
- `gjbot.subsystems.database_impl` 放資料庫實作。
- `database.py` 保留為舊 import 的兼容橋接。
- `gjbot.subsystems.storage` 透過套件路徑提供資料庫 API。
- `csharp/src/GJBot.BotServer` 提供 Windows 客戶端使用的控制 API，可執行消息、身份組、審核與頻道工具等 Discord 原生管理操作。
- `csharp/src/GJBot.ControlClient` 是 Windows WinForms 管理客戶端。
- `csharp/src/GJBot.Shared` 放 C# 後端與 Windows 客戶端共用的 DTO 與型別化 API 客戶端。

## 兼容原則

目前的重構不應移除既有指令、路由、模板、靜態資源、資料庫函式或支付行為。新增功能應優先放在 `gjbot/` 或 `csharp/` 對應模組內，再用小步驟把舊函式移到適配層後面，每一步都要能驗證。

## 驗證方式

建議在提交前執行：

```bash
python -m gjbot --check
python scripts/smoke_check.py
python -m py_compile role_manager_bot.py database.py music_cog.py alipay_callback_handler.py
dotnet build csharp/GJBot.CSharp.sln -c Debug
```

## 資料安全介面

新程式碼應優先使用具備交易安全的資料庫輔助函式：

- `database.db_apply_user_balance_delta(...)`
- `database.db_set_user_balance(...)`
- `database.db_decrement_shop_item_stock(...)`
- `database.db_update_recharge_request_status(...)`

舊函式仍然保留，讓現有 Bot 指令與 Web 路由可以在逐步遷移期間繼續正常工作。
