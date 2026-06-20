# GJBot C# Windows 控制客戶端

這個資料夾是一套 100% C# 的 Windows 控制方案，按現有 GJBot 文件與舊版 Web 面板功能補齊 Discord 控制端：

```text
[ GJBot.ControlClient WinForms ]
        |
        |  X-GJBot-Api-Key + JSON 控制指令
        v
[ GJBot.BotServer ASP.NET Core ]
        |
        |  Discord Bot Token + Discord REST API v10
        v
[ Discord 伺服器 ]
```

## 已完成的 C# 控制功能

對照原本 Python GJBot 的管理面板與斜線指令，目前 C# 版本已能直接控制 Discord REST API：

- 後端健康檢查、Bot 身份檢查、列出 Bot 所在伺服器。
- 網站功能中心：從 Windows 客戶端一鍵打開原 Web 面板所有功能頁，包括票據、音樂、AI 審核、經濟、備份、權限、副帳號與全域廣播。
- 載入伺服器總覽：伺服器、頻道、身份組。
- 消息/公告：單頻道文字消息、Embed 消息、批量廣播。
- 私信通知：對指定使用者發送 DM。
- 身份組：建立身份組、刪除身份組、授予成員身份組、移除成員身份組。
- 成員管理：禁言、解除禁言、踢出、封禁、解封。
- 頻道工具：修改頻道名稱、清除最近 1-100 則消息。
- 安全：Discord Bot Token 只放後端，Windows 客戶端只持有控制 API key。

原 Python bot 裡依賴 SQLite/記憶體/Socket.IO 的系統，例如票據客服、經濟商店、支付寶充值、AI 知識庫、音樂狀態與語音房主系統，仍由原 bot 處理。若要完全 C# 化，需要把那些資料表與長連線事件也遷移到 C#，這不是單純 Discord REST 呼叫能可靠完成的部分。

## 專案結構

```text
csharp/GJBot.CSharp.sln
csharp/src/GJBot.Shared          共用 DTO 與控制 API client
csharp/src/GJBot.BotServer       ASP.NET Core 後端，負責保存 Bot Token 並呼叫 Discord
csharp/src/GJBot.ControlClient   WinForms Windows 控制客戶端
```

## 開源協議

C# 控制端跟隨主專案使用 [MIT License](../LICENSE)。

## 需要安裝

- Windows 10/11
- .NET 8 SDK 或更新版
- Discord Bot Token
- Bot 已加入你的 Discord 伺服器，且具備目標操作需要的權限

本工作區已用本地 SDK 驗證過：

```powershell
E:\GJBOT\.dotnet\dotnet.exe build E:\GJBOT\csharp\GJBot.CSharp.sln -c Debug
```

## 後端啟動

```powershell
cd E:\GJBOT\csharp\src\GJBot.BotServer

dotnet user-secrets set "Discord:BotToken" "你的 Discord Bot Token"
dotnet user-secrets set "ControlApi:ApiKey" "換成一個很長的隨機密鑰"

dotnet run --urls "http://localhost:5088"
```

也可以用環境變數：

```powershell
$env:DISCORD_BOT_TOKEN="你的 Discord Bot Token"
$env:GJBOT_CONTROL_API_KEY="換成一個很長的隨機密鑰"
dotnet run --project E:\GJBOT\csharp\src\GJBot.BotServer --urls "http://localhost:5088"
```

如果只使用本工作區下載的本地 SDK：

```powershell
$env:DISCORD_BOT_TOKEN="你的 Discord Bot Token"
$env:GJBOT_CONTROL_API_KEY="換成一個很長的隨機密鑰"
E:\GJBOT\.dotnet\dotnet.exe run --project E:\GJBOT\csharp\src\GJBot.BotServer --urls "http://localhost:5088"
```

## 客戶端啟動

```powershell
dotnet run --project E:\GJBOT\csharp\src\GJBot.ControlClient
```

或：

```powershell
E:\GJBOT\.dotnet\dotnet.exe run --project E:\GJBOT\csharp\src\GJBot.ControlClient
```

在視窗中填：

- 後端地址：`http://localhost:5088`
- 網站地址：例如 `https://puneetblog.org`
- 控制 API Key：和後端 `ControlApi:ApiKey` 相同
- 伺服器 ID：目標 Discord guild ID
- 頻道 ID：常用文字頻道 ID

「網站功能中心」會使用網站地址打開原 Flask Web 面板。這些頁面仍需要原 Web 面板登入權限；如果 Cloudflare 對 `/control-api/` 有 Challenge，原生控制 API 會被擋，但網站功能中心打開的是一般 Web 頁面。

## 後端 API

所有 `/api/*` 路由都需要 Header：

```text
X-GJBot-Api-Key: 你的控制 API Key
```

主要路由：

```text
GET  /api/health
GET  /api/discord/me
GET  /api/discord/guilds
GET  /api/discord/guilds/{guildId}/overview
POST /api/discord/message
POST /api/discord/broadcast
POST /api/discord/dm
POST /api/discord/roles
POST /api/discord/roles/delete
POST /api/discord/members/roles/add
POST /api/discord/members/roles/remove
POST /api/discord/members/kick
POST /api/discord/members/ban
POST /api/discord/members/unban
POST /api/discord/members/timeout
POST /api/discord/members/timeout/remove
POST /api/discord/channels/rename
POST /api/discord/channels/messages/clear
```

## 發佈 Windows EXE

後端：

```powershell
dotnet publish E:\GJBOT\csharp\src\GJBot.BotServer -c Release -r win-x64 --self-contained false
```

客戶端：

```powershell
dotnet publish E:\GJBOT\csharp\src\GJBot.ControlClient -c Release -r win-x64 --self-contained false /p:PublishSingleFile=true
```

## 安全提醒

- 不要把 Discord Bot Token 寫進客戶端。
- 不要把 API key、Token、`appsettings.Production.json` 提交到 Git。
- 如果後端部署到外網，請使用 HTTPS，並限制防火牆來源 IP。
- 清消息只能批量刪除 Discord 允許的 14 天內消息。
- 客戶端 settings 存在 `%AppData%\GJBotControlClient\settings.json`，適合個人管理端使用。
