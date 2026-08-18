param(
    [string[]]$Models = @(),
    [ValidateSet("coinbase", "bybit")]
    [string]$Provider = "coinbase",
    [string[]]$Symbols = @("BTC-USD"),
    [string]$Timeframe = "5s",
    [ValidateRange(1, 3)]
    [int]$OpinionsPerRole = 1,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host "`nAURA SETUP STOPPED: $Message" -ForegroundColor Red
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

Write-Host "AURA AI OS - One Click Ollama + Multi-AI Launcher" -ForegroundColor Green
Write-Host "Mode: PUBLIC LIVE DATA + SHADOW/AI RESEARCH. Broker orders and real money remain disabled." -ForegroundColor Yellow

Write-Step "Checking Ollama"
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Fail "Ollama command was not found. Install/open Ollama first, then run START_AURA_OLLAMA.cmd again."
}

$ollamaUrl = "http://127.0.0.1:11434"
$tags = $null
try {
    $tags = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -Method Get -TimeoutSec 3
} catch {
    Write-Host "Ollama API is not running. Starting 'ollama serve'..." -ForegroundColor Yellow
    Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try {
            $tags = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -Method Get -TimeoutSec 3
            break
        } catch {
            # Keep trying while Ollama starts.
        }
    }
}
if (-not $tags) {
    Fail "Could not reach Ollama at $ollamaUrl. Open the Ollama app and try again."
}

$installedModels = @($tags.models | ForEach-Object { $_.name } | Where-Object { $_ })
if ($Models.Count -eq 0) {
    if ($installedModels.Count -eq 0) {
        Fail "Ollama is connected, but no local model is installed. Run 'ollama pull <model-name>' once, then launch AURA again."
    }
    $Models = @($installedModels | Select-Object -First 2)
}

$missing = @($Models | Where-Object { $_ -notin $installedModels })
if ($missing.Count -gt 0) {
    Write-Host "Missing requested Ollama model(s): $($missing -join ', ')" -ForegroundColor Yellow
    foreach ($model in $missing) {
        Write-Host "Pulling $model ..." -ForegroundColor Yellow
        & $ollama.Source pull $model
        if ($LASTEXITCODE -ne 0) {
            Fail "Could not pull Ollama model '$model'."
        }
    }
}

Write-Host "Ollama connected. AURA models: $($Models -join ', ')" -ForegroundColor Green

Write-Step "Preparing Python environment"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            & $py.Source -3 -m venv .venv
        }
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            Fail "Python was not found. Install Python 3.11 or 3.12 first."
        }
        & $python.Source -m venv .venv
    }
}
if (-not (Test-Path $venvPython)) {
    Fail "AURA virtual environment could not be created."
}

if (-not $SkipDependencyInstall) {
    & $venvPython -c "import aura" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing AURA dependencies (first run only)..." -ForegroundColor Yellow
        & $venvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed." }
        & $venvPython -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { Fail "AURA dependency installation failed." }
    }
}

Write-Step "Configuring AURA Multi-AI council"
$env:AURA_OLLAMA_URL = $ollamaUrl
$env:AURA_OLLAMA_MODELS = ($Models -join ",")
$env:AURA_AI_OPINIONS_PER_ROLE = [string]$OpinionsPerRole
$env:AURA_OLLAMA_THINK = "false"
$env:AURA_OLLAMA_TIMEOUT_SECONDS = "120"
$env:AURA_OLLAMA_MAX_CONCURRENCY = "1"
$env:AURA_AI_AGENT_TIMEOUT_SECONDS = "240"
$env:AURA_LIVE_TRADING_ENABLED = ""
$env:AURA_HUMAN_LIVE_APPROVAL_ID = ""

Write-Host "AURA_OLLAMA_MODELS=$env:AURA_OLLAMA_MODELS" -ForegroundColor Green
Write-Host "AI opinions per role=$OpinionsPerRole" -ForegroundColor Green

Write-Step "Running fail-closed AURA production preflight"
& $venvPython "examples/run_production_preflight.py" --mode paper --connector public
if ($LASTEXITCODE -ne 0) {
    Fail "Production preflight failed. AURA was not started."
}

Write-Step "Starting AURA public live Multi-AI Council"
Write-Host "Provider: $Provider | Symbols: $($Symbols -join ', ') | Timeframe: $Timeframe" -ForegroundColor Green
Write-Host "Press Ctrl+C when you want to stop the local session." -ForegroundColor DarkGray

$runArgs = @(
    "examples/run_free_public_ai_council.py",
    "--provider", $Provider,
    "--symbols"
) + $Symbols + @(
    "--timeframe", $Timeframe,
    "--min-history-bars", "30",
    "--analyze-every-bars", "5",
    "--max-inflight-ai-decisions", "1"
)

& $venvPython @runArgs
exit $LASTEXITCODE
