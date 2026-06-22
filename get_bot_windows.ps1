param(
    [ValidateSet("Local", "Server", "Start", "Stop", "Restart", "Status", "Uninstall")]
    [string]$Mode = "Local",

    [string]$ProjectDir = "",
    [string]$RepoUrl = "https://github.com/PuneetGOTO/2026.6-14-MYDCBOT.git",
    [string]$ServiceName = "GJBot",
    [string]$NssmPath = "",

    [switch]$DownloadNssm,
    [switch]$SkipEnvPrompt,
    [switch]$SkipSmokeCheck,
    [switch]$NoStart,
    [switch]$ForceEnv,
    [switch]$OpenFirewall,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
}
catch {
    # Older hosts may not allow changing the console encoding. Python env vars above are the important part.
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Show-Usage {
    Write-Host @"
GJBot Windows runner

Local foreground run:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Local

Windows Server service install with NSSM:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Server -ProjectDir C:\GJTEAM-BOT -DownloadNssm

Service management:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Status
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Start
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Stop
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Restart
  powershell -NoProfile -ExecutionPolicy Bypass -File .\get_bot_windows.ps1 -Mode Uninstall

If Windows says the script is not digitally signed, do not dot-source the file.
Run it with -ExecutionPolicy Bypass as shown above, or unblock it once:
  Unblock-File .\get_bot_windows.ps1

Useful switches:
  -NoStart          Set up only; do not start the bot or service.
  -SkipEnvPrompt   Do not create .env interactively.
  -ForceEnv        Recreate .env even if it already exists.
  -DownloadNssm    Download NSSM to ProgramData if nssm.exe is not found.
  -OpenFirewall    Add inbound rules for ports 5000 and 8080.
"@
}

function Get-DefaultProjectDir {
    if ($PSScriptRoot) {
        return $PSScriptRoot
    }

    return (Get-Location).Path
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Require-Admin {
    if (-not (Test-Admin)) {
        throw "Mode '$Mode' must be run from an Administrator PowerShell window."
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    $oldLocation = Get-Location
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        if ($WorkingDirectory) {
            Set-Location -LiteralPath $WorkingDirectory
        }

        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            Write-Host $_
        }

        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        Set-Location $oldLocation
    }
}

function Test-ProjectDirectory {
    param([string]$Path)

    $entryPoint = Join-Path $Path "gjbot\__main__.py"
    $requirements = Join-Path $Path "requirements.txt"
    return ((Test-Path -LiteralPath $entryPoint) -and (Test-Path -LiteralPath $requirements))
}

function Ensure-ProjectDirectory {
    if (Test-ProjectDirectory $ProjectDir) {
        Write-Success "Project directory found: $ProjectDir"
        return
    }

    if (-not (Test-CommandExists "git")) {
        throw "Git is required when ProjectDir does not already contain the project."
    }

    if (Test-Path -LiteralPath $ProjectDir) {
        $items = @(Get-ChildItem -LiteralPath $ProjectDir -Force)
        if ($items.Count -gt 0) {
            throw "ProjectDir exists but is not a GJBot checkout: $ProjectDir"
        }
    }
    else {
        $parent = Split-Path -Parent $ProjectDir
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
    }

    Write-Info "Cloning project from $RepoUrl to $ProjectDir"
    $cloneParent = Split-Path -Parent $ProjectDir
    if (-not $cloneParent) {
        $cloneParent = (Get-Location).Path
    }

    Invoke-Checked -FilePath "git" -Arguments @("clone", $RepoUrl, $ProjectDir) -WorkingDirectory $cloneParent
    Write-Success "Project cloned."
}

function Ensure-Venv {
    $venvDir = Join-Path $ProjectDir "venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Test-Path -LiteralPath $venvDir) {
            throw "The venv folder exists but python.exe is missing. Remove '$venvDir' or choose a clean ProjectDir."
        }

        Write-Info "Creating Python virtual environment..."
        if (Test-CommandExists "py") {
            Invoke-Checked -FilePath "py" -Arguments @("-3", "-m", "venv", $venvDir) -WorkingDirectory $ProjectDir
        }
        elseif (Test-CommandExists "python") {
            Invoke-Checked -FilePath "python" -Arguments @("-m", "venv", $venvDir) -WorkingDirectory $ProjectDir
        }
        else {
            throw "Python 3 was not found. Install Python and make sure 'py' or 'python' is available in PATH."
        }
    }
    else {
        Write-Success "Virtual environment found."
    }

    Write-Info "Installing Python dependencies..."
    Invoke-Checked -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -WorkingDirectory $ProjectDir
    Invoke-Checked -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $ProjectDir "requirements.txt")) -WorkingDirectory $ProjectDir
    Write-Success "Python dependencies installed."

    return $venvPython
}

function Convert-SecureStringToPlainText {
    param([securestring]$SecureString)

    if (-not $SecureString) {
        return ""
    }

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Read-TextValue {
    param(
        [string]$Prompt,
        [string]$Default = ""
    )

    if ($Default) {
        $value = Read-Host "$Prompt [$Default]"
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $Default
        }

        return $value
    }

    return (Read-Host $Prompt)
}

function Read-SecretValue {
    param([string]$Prompt)

    $secure = Read-Host $Prompt -AsSecureString
    return Convert-SecureStringToPlainText $secure
}

function New-RandomHex {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }

    return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function ConvertTo-DotEnvValue {
    param([string]$Value)

    $text = [string]$Value
    $text = $text.Replace("\", "\\").Replace("'", "\'").Replace("`r", "").Replace("`n", "\n")
    return "'$text'"
}

function Add-DotEnvLine {
    param(
        [string[]]$Lines,
        [string]$Name,
        [string]$Value,
        [switch]$Optional
    )

    if ($Optional -and [string]::IsNullOrWhiteSpace($Value)) {
        return $Lines
    }

    return ($Lines + "$Name=$(ConvertTo-DotEnvValue $Value)")
}

function Ensure-EnvFile {
    param([switch]$ServerMode)

    $envPath = Join-Path $ProjectDir ".env"
    if ((Test-Path -LiteralPath $envPath) -and -not $ForceEnv) {
        Write-Success ".env already exists. Use -ForceEnv to recreate it."
        return
    }

    if ($SkipEnvPrompt) {
        Write-Warn "Skipping .env creation. The bot will not start until required environment variables are set."
        return
    }

    $answer = Read-TextValue -Prompt "Create .env interactively now? (Y/n)" -Default "Y"
    if ($answer -match "^(n|no)$") {
        Write-Warn ".env was not created."
        return
    }

    $discordToken = Read-SecretValue "Discord bot token"
    $restartPassword = Read-SecretValue "Bot restart password (optional)"
    $webAdminPassword = Read-SecretValue "Web admin password"
    $discordClientId = Read-TextValue "Discord OAuth client ID" ""
    $discordClientSecret = Read-SecretValue "Discord OAuth client secret"

    $domain = Read-TextValue "Public domain for callback URLs (blank for local defaults)" ""
    if ([string]::IsNullOrWhiteSpace($domain)) {
        $redirectUri = "http://127.0.0.1:5000/callback"
        $notifyUrl = "http://127.0.0.1:8080/alipay/notify"
    }
    else {
        $defaultScheme = "http"
        if ($ServerMode) {
            $defaultScheme = "https"
        }

        $scheme = Read-TextValue "URL scheme" $defaultScheme
        $redirectUri = "${scheme}://${domain}/callback"
        $notifyUrl = "${scheme}://${domain}/alipay/notify"
    }

    $port = Read-TextValue "Web panel port" "5000"
    $alipayCallbackPort = Read-TextValue "Alipay callback port" "8080"
    $deepSeekKey = Read-SecretValue "DeepSeek API key (optional)"
    $alipayAppId = Read-TextValue "Alipay app ID (optional)" ""
    $alipayPrivateKeyPath = Read-TextValue "Alipay private key path (optional)" ""
    $alipayPublicKeyForSdk = Read-TextValue "Alipay SDK public key content (optional)" ""
    $alipayCallbackPublicKey = Read-TextValue "Alipay callback verify public key content (optional)" ""
    $rechargeChannel = Read-TextValue "Recharge admin notification channel ID (optional)" ""

    $lines = @("# Auto-generated by get_bot_windows.ps1")
    $lines = Add-DotEnvLine $lines "DISCORD_BOT_TOKEN" $discordToken
    $lines = Add-DotEnvLine $lines "BOT_RESTART_PASSWORD" $restartPassword -Optional
    $lines = Add-DotEnvLine $lines "FLASK_SECRET_KEY" (New-RandomHex)
    $lines = Add-DotEnvLine $lines "WEB_ADMIN_PASSWORD" $webAdminPassword
    $lines = Add-DotEnvLine $lines "DISCORD_CLIENT_ID" $discordClientId
    $lines = Add-DotEnvLine $lines "DISCORD_CLIENT_SECRET" $discordClientSecret
    $lines = Add-DotEnvLine $lines "DISCORD_REDIRECT_URI" $redirectUri
    $lines = Add-DotEnvLine $lines "PORT" $port
    $lines = Add-DotEnvLine $lines "ALIPAY_CALLBACK_PORT" $alipayCallbackPort
    $lines = Add-DotEnvLine $lines "DEEPSEEK_API_KEY" $deepSeekKey -Optional
    $lines = Add-DotEnvLine $lines "ALIPAY_APP_ID" $alipayAppId -Optional
    $lines = Add-DotEnvLine $lines "ALIPAY_PRIVATE_KEY_PATH" $alipayPrivateKeyPath -Optional
    $lines = Add-DotEnvLine $lines "ALIPAY_PUBLIC_KEY_FOR_SDK_CONTENT" $alipayPublicKeyForSdk -Optional
    $lines = Add-DotEnvLine $lines "ALIPAY_PUBLIC_KEY_CONTENT_FOR_CALLBACK_VERIFY" $alipayCallbackPublicKey -Optional
    $lines = Add-DotEnvLine $lines "ALIPAY_NOTIFY_URL" $notifyUrl
    $lines = Add-DotEnvLine $lines "RECHARGE_ADMIN_NOTIFICATION_CHANNEL_ID" $rechargeChannel -Optional
    $lines = Add-DotEnvLine $lines "RECHARGE_CONVERSION_RATE" "100"
    $lines = Add-DotEnvLine $lines "ECONOMY_DEFAULT_BALANCE" "100"
    $lines = Add-DotEnvLine $lines "MIN_RECHARGE_AMOUNT" "1.0"
    $lines = Add-DotEnvLine $lines "MAX_RECHARGE_AMOUNT" "10000.0"

    Set-Content -LiteralPath $envPath -Value $lines -Encoding UTF8
    Write-Success ".env created at $envPath"
}

function Run-ProjectChecks {
    param([string]$VenvPython)

    if ($SkipSmokeCheck) {
        Write-Warn "Skipping project checks."
        return
    }

    Write-Info "Running project checks..."
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "gjbot", "--check") -WorkingDirectory $ProjectDir
    Invoke-Checked -FilePath $VenvPython -Arguments @("scripts\smoke_check.py") -WorkingDirectory $ProjectDir
    Write-Success "Project checks passed."
}

function Resolve-NssmPath {
    param([switch]$AllowMissing)

    if ($NssmPath) {
        $resolved = [System.IO.Path]::GetFullPath($NssmPath)
        if (Test-Path -LiteralPath $resolved) {
            return $resolved
        }

        throw "NSSM was not found at: $resolved"
    }

    $command = Get-Command "nssm.exe" -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command "nssm" -ErrorAction SilentlyContinue
    }

    if ($command) {
        return $command.Source
    }

    $defaultNssm = "C:\nssm\nssm.exe"
    if (Test-Path -LiteralPath $defaultNssm) {
        return $defaultNssm
    }

    $programData = $env:ProgramData
    if (-not $programData) {
        $programData = "C:\ProgramData"
    }

    $downloadedNssm = Join-Path $programData "GJBot\nssm\nssm.exe"
    if (Test-Path -LiteralPath $downloadedNssm) {
        return $downloadedNssm
    }

    if ($DownloadNssm) {
        Write-Info "Downloading NSSM..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        $zipUrl = "https://nssm.cc/release/nssm-2.24.zip"
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("gjbot-nssm-" + [Guid]::NewGuid().ToString("N"))
        $zipPath = Join-Path $tempRoot "nssm.zip"
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        Expand-Archive -LiteralPath $zipPath -DestinationPath $tempRoot -Force

        $arch = "win32"
        if ([Environment]::Is64BitOperatingSystem) {
            $arch = "win64"
        }

        $source = Join-Path $tempRoot "nssm-2.24\$arch\nssm.exe"
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Downloaded NSSM archive did not contain $arch\nssm.exe"
        }

        $targetDir = Split-Path -Parent $downloadedNssm
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $downloadedNssm -Force
        Write-Success "NSSM installed at $downloadedNssm"
        return $downloadedNssm
    }

    if ($AllowMissing) {
        return $null
    }

    throw "NSSM was not found. Install it at C:\nssm\nssm.exe, pass -NssmPath, or add -DownloadNssm."
}

function Install-GJBotService {
    param(
        [string]$VenvPython,
        [string]$ResolvedNssmPath
    )

    $logsDir = Join-Path $ProjectDir "logs"
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        Write-Info "Service '$ServiceName' already exists. Updating NSSM settings..."
    }
    else {
        Write-Info "Installing Windows service '$ServiceName'..."
        Invoke-Checked -FilePath $ResolvedNssmPath -Arguments @("install", $ServiceName, $VenvPython, "-m", "gjbot")
    }

    $stdoutLog = Join-Path $logsDir "gjbot.out.log"
    $stderrLog = Join-Path $logsDir "gjbot.err.log"

    $settings = @(
        ,@("set", $ServiceName, "Application", $VenvPython),
        ,@("set", $ServiceName, "AppParameters", "-m gjbot"),
        ,@("set", $ServiceName, "AppDirectory", $ProjectDir),
        ,@("set", $ServiceName, "DisplayName", "GJBot Discord Bot and Web Panel"),
        ,@("set", $ServiceName, "Description", "Runs the GJBot Discord bot, Flask web panel, and payment callback listener."),
        ,@("set", $ServiceName, "Start", "SERVICE_AUTO_START"),
        ,@("set", $ServiceName, "AppStdout", $stdoutLog),
        ,@("set", $ServiceName, "AppStderr", $stderrLog),
        ,@("set", $ServiceName, "AppRotateFiles", "1"),
        ,@("set", $ServiceName, "AppRotateOnline", "1"),
        ,@("set", $ServiceName, "AppRotateSeconds", "86400"),
        ,@("set", $ServiceName, "AppRotateBytes", "10485760"),
        ,@("set", $ServiceName, "AppRestartDelay", "10000"),
        ,@("set", $ServiceName, "AppEnvironmentExtra", "PYTHONUNBUFFERED=1", "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
    )

    foreach ($setting in $settings) {
        Invoke-Checked -FilePath $ResolvedNssmPath -Arguments $setting
    }

    Write-Success "Windows service is configured."
}

function Ensure-FirewallRules {
    if (-not $OpenFirewall) {
        return
    }

    Write-Info "Adding Windows Firewall rules for ports 5000 and 8080..."
    try {
        $rules = @(
            ,@("GJBot Web Panel 5000", 5000),
            ,@("GJBot Alipay Callback 8080", 8080)
        )

        foreach ($rule in $rules) {
            $displayName = $rule[0]
            $port = $rule[1]
            if (-not (Get-NetFirewallRule -DisplayName $displayName -ErrorAction SilentlyContinue)) {
                New-NetFirewallRule -DisplayName $displayName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Any | Out-Null
            }
        }

        Write-Success "Firewall rules are ready."
    }
    catch {
        Write-Warn "Could not update firewall rules: $($_.Exception.Message)"
    }
}

function Show-ServiceStatus {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Warn "Service '$ServiceName' is not installed."
        return
    }

    Write-Host "Name:   $($service.Name)"
    Write-Host "Status: $($service.Status)"

    try {
        $escapedName = $ServiceName.Replace("'", "''")
        $details = Get-CimInstance Win32_Service -Filter "Name='$escapedName'"
        if ($details) {
            Write-Host "Start:  $($details.StartMode)"
            Write-Host "Path:   $($details.PathName)"
        }
    }
    catch {
        Write-Warn "Could not read service details: $($_.Exception.Message)"
    }
}

function Start-GJBotService {
    Require-Admin
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "Service '$ServiceName' is not installed."
    }

    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 2
    Show-ServiceStatus
}

function Stop-GJBotService {
    Require-Admin
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "Service '$ServiceName' is not installed."
    }

    Stop-Service -Name $ServiceName -Force
    Start-Sleep -Seconds 2
    Show-ServiceStatus
}

function Restart-GJBotService {
    Require-Admin
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "Service '$ServiceName' is not installed."
    }

    Restart-Service -Name $ServiceName -Force
    Start-Sleep -Seconds 2
    Show-ServiceStatus
}

function Uninstall-GJBotService {
    Require-Admin
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Warn "Service '$ServiceName' is not installed."
        return
    }

    if ($service.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
        Start-Sleep -Seconds 2
    }

    $resolvedNssm = Resolve-NssmPath -AllowMissing
    if ($resolvedNssm) {
        Invoke-Checked -FilePath $resolvedNssm -Arguments @("remove", $ServiceName, "confirm")
    }
    else {
        Invoke-Checked -FilePath "sc.exe" -Arguments @("delete", $ServiceName)
    }

    Write-Success "Service '$ServiceName' was removed."
}

function Show-ServerNotes {
    Write-Host @"

Windows Server notes
--------------------
Service logs:
  $ProjectDir\logs\gjbot.out.log
  $ProjectDir\logs\gjbot.err.log

For public access, put Caddy, Nginx for Windows, or IIS ARR in front of the bot
and terminate HTTPS there. When the reverse proxy runs on the same server, point
it to 127.0.0.1:5000. The Alipay callback listener uses 8080 by default.

Caddyfile example:
  bot.example.com {
      reverse_proxy 127.0.0.1:5000

      handle_path /alipay/notify {
          reverse_proxy 127.0.0.1:8080
      }
  }

Socket.IO uses /my-custom-socket-path, so the reverse proxy must support
WebSocket upgrades.
"@
}

try {
    if ($Help) {
        Show-Usage
        exit 0
    }

    if ($env:OS -and $env:OS -ne "Windows_NT") {
        throw "This script is intended for Windows PowerShell."
    }

    if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
        $ProjectDir = Get-DefaultProjectDir
    }

    $ProjectDir = [System.IO.Path]::GetFullPath($ProjectDir)

    switch ($Mode) {
        "Status" {
            Show-ServiceStatus
        }
        "Start" {
            Start-GJBotService
        }
        "Stop" {
            Stop-GJBotService
        }
        "Restart" {
            Restart-GJBotService
        }
        "Uninstall" {
            Uninstall-GJBotService
        }
        "Local" {
            Ensure-ProjectDirectory
            $venvPython = Ensure-Venv
            Ensure-EnvFile
            Run-ProjectChecks -VenvPython $venvPython

            if ($NoStart) {
                Write-Success "Local setup complete. Start later with: $venvPython -m gjbot"
            }
            else {
                Write-Info "Starting GJBot in the foreground. Press Ctrl+C to stop."
                Invoke-Checked -FilePath $venvPython -Arguments @("-m", "gjbot") -WorkingDirectory $ProjectDir
            }
        }
        "Server" {
            Require-Admin
            Ensure-ProjectDirectory
            $venvPython = Ensure-Venv
            Ensure-EnvFile -ServerMode
            Run-ProjectChecks -VenvPython $venvPython

            $resolvedNssm = Resolve-NssmPath
            Install-GJBotService -VenvPython $venvPython -ResolvedNssmPath $resolvedNssm
            Ensure-FirewallRules

            if ($NoStart) {
                Write-Success "Server setup complete. Start later with: .\get_bot_windows.ps1 -Mode Start"
            }
            else {
                Start-GJBotService
            }

            Show-ServerNotes
        }
    }
}
catch {
    Write-Fail $_.Exception.Message
    exit 1
}
