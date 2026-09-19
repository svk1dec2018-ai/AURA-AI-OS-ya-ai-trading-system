$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AURA LOCAL FREE / UNLIMITED AI SETUP" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This installs LOCAL Ollama models only." -ForegroundColor Green
Write-Host "Local inference has no per-token/API charge; usage is limited by your own PC resources." -ForegroundColor Green
Write-Host ""

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Ollama is missing and winget is unavailable. Install Ollama manually, then rerun this file."
    }
    Write-Host "Installing Ollama for Windows..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama installation failed."
    }

    $PossiblePaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama"),
        (Join-Path $env:LOCALAPPDATA "Ollama"),
        "C:\Program Files\Ollama"
    )
    foreach ($Path in $PossiblePaths) {
        if (Test-Path (Join-Path $Path "ollama.exe")) {
            $env:Path = $Path + ";" + $env:Path
            break
        }
    }
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama was installed but the command is not visible yet. Sign out/in once or reopen Windows Terminal, then rerun."
}

$OllamaReady = $false
try {
    & ollama list *> $null
    if ($LASTEXITCODE -eq 0) { $OllamaReady = $true }
} catch {}

if (-not $OllamaReady) {
    Write-Host "Starting local Ollama API..." -ForegroundColor Yellow
    Start-Process -FilePath (Get-Command ollama).Source -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        & ollama list *> $null
        if ($LASTEXITCODE -eq 0) {
            $OllamaReady = $true
            break
        }
    }
}
if (-not $OllamaReady) {
    throw "Ollama local API did not become ready on localhost."
}

$Models = @(
    "qwen3.5:4b",
    "deepseek-r1:8b",
    "llama3.1:8b",
    "gemma3:4b",
    "phi4-mini:3.8b"
)

Write-Host ""
Write-Host "AURA balanced5 local council will download about 19 GB in total." -ForegroundColor Yellow
Write-Host "Models are pulled one-by-one so memory pressure stays controlled." -ForegroundColor Yellow
Write-Host ""

foreach ($Model in $Models) {
    Write-Host ("Pulling " + $Model + " ...") -ForegroundColor Cyan
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        throw ("Failed to pull local model: " + $Model)
    }
}

$EnvFile = Join-Path $Root ".env.local"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
}

$Lines = Get-Content -LiteralPath $EnvFile
$FoundPreset = $false
$Updated = foreach ($Line in $Lines) {
    if ($Line -match "^AURA_FREE_AI_PRESET=") {
        $FoundPreset = $true
        "AURA_FREE_AI_PRESET=balanced5"
    } else {
        $Line
    }
}
if (-not $FoundPreset) {
    $Updated += "AURA_FREE_AI_PRESET=balanced5"
}
Set-Content -LiteralPath $EnvFile -Value $Updated -Encoding UTF8

Write-Host ""
Write-Host "AURA LOCAL FREE AI READY" -ForegroundColor Green
Write-Host "Provider: Ollama local API http://127.0.0.1:11434" -ForegroundColor Green
Write-Host "Preset: balanced5" -ForegroundColor Green
Write-Host "API key: NOT REQUIRED" -ForegroundColor Green
Write-Host "Per-token charge: NONE for local inference" -ForegroundColor Green
Write-Host ""
Write-Host "Cloud free APIs are not labeled unlimited because they publish usage/rate limits."
