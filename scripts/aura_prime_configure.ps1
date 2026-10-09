param(
    [string]$EnvPath = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $EnvPath) { $EnvPath = Join-Path $Root ".env.local" }
$Example = Join-Path $Root ".env.example"

if (-not (Test-Path $EnvPath)) {
    Copy-Item $Example $EnvPath
}

function ConvertFrom-Secure([Security.SecureString]$Value) {
    $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr)
    }
}

function Set-AuraEnv([string]$Name, [string]$Value) {
    if ($Value.Contains([char]0) -or $Value.Contains("`r") -or $Value.Contains("`n")) {
        throw ("AURA env value for " + $Name + " must be a single line")
    }
    $Lines = @(Get-Content -LiteralPath $EnvPath -ErrorAction Stop)
    $Replacement = $Name + "=" + $Value
    $Found = $false
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match ("^" + [regex]::Escape($Name) + "=")) {
            $Lines[$i] = $Replacement
            $Found = $true
            break
        }
    }
    if (-not $Found) {
        $Lines += $Replacement
    }
    Set-Content -LiteralPath $EnvPath -Value $Lines -Encoding UTF8
}

function Read-Required([string]$Prompt) {
    while ($true) {
        $Value = Read-Host $Prompt
        if ($Value.Trim()) { return $Value.Trim() }
        Write-Host "Value required." -ForegroundColor Yellow
    }
}

function Read-Secret([string]$Prompt) {
    while ($true) {
        $Secure = Read-Host $Prompt -AsSecureString
        $Value = ConvertFrom-Secure $Secure
        if ($Value.Trim()) { return $Value.Trim() }
        Write-Host "Value required." -ForegroundColor Yellow
    }
}

function Test-LocalPort([int]$Port) {
    try {
        $Client = New-Object System.Net.Sockets.TcpClient
        $Async = $Client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $Ready = $Async.AsyncWaitHandle.WaitOne(500)
        if (-not $Ready) {
            $Client.Close()
            return $false
        }
        $Client.EndConnect($Async)
        $Client.Close()
        return $true
    } catch {
        return $false
    }
}

function Configure-LocalAI {
    if (Test-LocalPort 20128) {
        Write-Host "OmniRoute detected on localhost:20128." -ForegroundColor Green
        Set-AuraEnv "AURA_COMPAT_BASE_URL" "http://127.0.0.1:20128/v1"
        $Model = Read-Host "OmniRoute model [auto/best-coding]"
        if (-not $Model.Trim()) { $Model = "auto/best-coding" }
        Set-AuraEnv "AURA_COMPAT_MODEL" $Model.Trim()
        Set-AuraEnv "AURA_MAINTENANCE_AI_PROVIDER" "compatible"
        Write-Host "Local OmniRoute configured. No AURA API key required." -ForegroundColor Green
        return
    }
    if (Test-LocalPort 11434) {
        Write-Host "Ollama detected on localhost:11434." -ForegroundColor Green
        Set-AuraEnv "AURA_OLLAMA_URL" "http://127.0.0.1:11434"
        Set-AuraEnv "AURA_FREE_AI_PRESET" "balanced5"
        Set-AuraEnv "AURA_MAINTENANCE_AI_PROVIDER" "ollama"
        Write-Host "Local Ollama configured. No API key required." -ForegroundColor Green
        return
    }
    Write-Warning "No local OmniRoute or Ollama service detected."
}

while ($true) {
    Clear-Host
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "       AURA PRIME - PRIVATE CREDENTIAL WIZARD" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "Secrets are written only to .env.local and are never printed."
    Write-Host ""
    Write-Host " [1] Detect/configure local AI (OmniRoute or Ollama)"
    Write-Host " [2] MT5 DEMO account"
    Write-Host " [3] Dhan India market data"
    Write-Host " [4] Angel One SmartAPI"
    Write-Host " [5] Shoonya"
    Write-Host " [6] Flattrade"
    Write-Host " [7] OANDA practice"
    Write-Host " [8] OpenRouter direct / compatible cloud"
    Write-Host " [9] Telegram alerts"
    Write-Host " [G] Groq free-tier AI"
    Write-Host " [N] NVIDIA NIM AI"
    Write-Host " [M] Google Gemini AI"
    Write-Host " [F] Optional FRED + Alpha Vantage"
    Write-Host " [Q] Done"
    Write-Host ""
    $Choice = Read-Host "Select"

    switch ($Choice.ToUpperInvariant()) {
        "1" {
            Configure-LocalAI
        }
        "2" {
            Set-AuraEnv "AURA_MT5_DEMO_LOGIN" (Read-Required "MT5 DEMO login")
            Set-AuraEnv "AURA_MT5_DEMO_PASSWORD" (Read-Secret "MT5 DEMO password")
            Set-AuraEnv "AURA_MT5_DEMO_SERVER" (Read-Required "MT5 DEMO server")
            $Terminal = Read-Host "MT5 terminal path (optional)"
            if ($Terminal.Trim()) { Set-AuraEnv "AURA_MT5_TERMINAL_PATH" $Terminal.Trim() }
        }
        "3" {
            Set-AuraEnv "AURA_DHAN_CLIENT_ID" (Read-Required "Dhan client ID")
            Set-AuraEnv "AURA_DHAN_ACCESS_TOKEN" (Read-Secret "Dhan access token")
        }
        "4" {
            Set-AuraEnv "AURA_ANGEL_ONE_API_KEY" (Read-Secret "Angel One API key")
            Set-AuraEnv "AURA_ANGEL_ONE_CLIENT_CODE" (Read-Required "Angel One client code")
            Set-AuraEnv "AURA_ANGEL_ONE_JWT_TOKEN" (Read-Secret "Angel One JWT token")
            Set-AuraEnv "AURA_ANGEL_ONE_REFRESH_TOKEN" (Read-Secret "Angel One refresh token")
            $Feed = Read-Host "Angel One feed token (optional)"
            if ($Feed.Trim()) { Set-AuraEnv "AURA_ANGEL_ONE_FEED_TOKEN" $Feed.Trim() }
        }
        "5" {
            Set-AuraEnv "AURA_SHOONYA_USER_ID" (Read-Required "Shoonya user ID")
            Set-AuraEnv "AURA_SHOONYA_ACCOUNT_ID" (Read-Required "Shoonya account ID")
            Set-AuraEnv "AURA_SHOONYA_SESSION_TOKEN" (Read-Secret "Shoonya session token")
        }
        "6" {
            Set-AuraEnv "AURA_FLATTRADE_USER_ID" (Read-Required "Flattrade user ID")
            Set-AuraEnv "AURA_FLATTRADE_ACCOUNT_ID" (Read-Required "Flattrade account ID")
            Set-AuraEnv "AURA_FLATTRADE_ACCESS_TOKEN" (Read-Secret "Flattrade access token")
        }
        "7" {
            Set-AuraEnv "AURA_OANDA_ACCOUNT_ID" (Read-Required "OANDA practice account ID")
            Set-AuraEnv "AURA_OANDA_ACCESS_TOKEN" (Read-Secret "OANDA practice access token")
            Set-AuraEnv "AURA_OANDA_ENVIRONMENT" "practice"
        }
        "8" {
            Set-AuraEnv "AURA_COMPAT_BASE_URL" "https://openrouter.ai/api/v1"
            $Model = Read-Host "OpenRouter model [openrouter/free]"
            if (-not $Model.Trim()) { $Model = "openrouter/free" }
            Set-AuraEnv "AURA_COMPAT_MODEL" $Model.Trim()
            Set-AuraEnv "AURA_COMPAT_API_KEY" (Read-Secret "OpenRouter API key")
            Set-AuraEnv "AURA_MAINTENANCE_AI_PROVIDER" "compatible"
        }
        "9" {
            Set-AuraEnv "AURA_TELEGRAM_BOT_TOKEN" (Read-Secret "Telegram bot token")
            Set-AuraEnv "AURA_TELEGRAM_CHAT_ID" (Read-Required "Telegram chat ID")
        }
        "G" { Set-AuraEnv "GROQ_API_KEY" (Read-Secret "Groq API key") }
        "N" { Set-AuraEnv "NVIDIA_API_KEY" (Read-Secret "NVIDIA API key") }
        "M" { Set-AuraEnv "GEMINI_API_KEY" (Read-Secret "Gemini API key") }
        "F" {
            $Fred = Read-Host "FRED API key (blank to skip)"
            if ($Fred.Trim()) { Set-AuraEnv "AURA_FRED_API_KEY" $Fred.Trim() }
            $Alpha = Read-Host "Alpha Vantage API key (blank to skip)"
            if ($Alpha.Trim()) { Set-AuraEnv "AURA_ALPHA_VANTAGE_API_KEY" $Alpha.Trim() }
        }
        "Q" {
            Write-Host "AURA private configuration saved to $EnvPath" -ForegroundColor Green
            break
        }
        default {
            Write-Host "Unknown choice." -ForegroundColor Yellow
        }
    }
    if ($Choice.ToUpperInvariant() -eq "Q") { break }
    Write-Host ""
    Pause
}
