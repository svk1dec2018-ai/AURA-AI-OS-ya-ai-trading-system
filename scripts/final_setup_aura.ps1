$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Dashboard = Join-Path $Root "dashboard"
$EnvFile = Join-Path $Root ".env.local"

Set-Location $Root
. (Join-Path $PSScriptRoot "aura_env.ps1")

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AURA FINAL PRODUCTION SETUP" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & py -3.12 -m venv $VenvDir
        } else {
            & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                & py -3.11 -m venv $VenvDir
            }
        }
    }
}

if (-not (Test-Path $VenvPython)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.11+ missing and winget is unavailable."
    }
    Write-Host "Installing Python 3.12..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    & py -3.12 -m venv $VenvDir
}

Write-Host "Installing AURA backend, dev checks, distributed fleet and MT5 bridge..."
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
& $VenvPython -m pip install --disable-pip-version-check -e ".[dev,distributed,mt5]"
if ($LASTEXITCODE -ne 0) { throw "AURA Python dependency setup failed." }

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Node.js 20+ missing and winget is unavailable."
    }
    Write-Host "Installing Node.js LTS..." -ForegroundColor Yellow
    winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
    $env:Path = "C:\Program Files\nodejs;" + $env:Path
}

$NodeMajor = [int](& node -p "process.versions.node.split('.')[0]")
if ($NodeMajor -lt 20) { throw "Node.js 20 or newer is required." }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Docker Desktop is not installed. Installing Docker Desktop..." -ForegroundColor Yellow
        winget install --id Docker.DockerDesktop -e --source winget --accept-package-agreements --accept-source-agreements
        Write-Host "If Docker Desktop requests logout/restart, complete that once before START_AURA_PRODUCTION.cmd." -ForegroundColor Yellow
    } else {
        Write-Warning "Docker Desktop is missing. Install it before starting the distributed fleet."
    }
}

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
    Write-Host "Created private .env.local from template." -ForegroundColor Green
} else {
    Write-Host ".env.local already exists; existing values were preserved."
}
Import-AuraEnv -Path $EnvFile

Write-Host "Installing dashboard packages..."
Push-Location $Dashboard
& npm.cmd install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Dashboard npm install failed." }
& npm.cmd run build
$DashboardBuild = $LASTEXITCODE
Pop-Location
if ($DashboardBuild -ne 0) { throw "Dashboard production build failed." }

Write-Host "Running AURA repository verification..."
& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed." }
& $VenvPython -m ruff check aura tests examples
if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }

# Unit tests must not inherit real/local AI provider configuration from .env.local.
# Otherwise pytest can accidentally call Ollama/OpenAI and time out or become
# non-deterministic. Save the values, clear them for verification, then restore.
$TestEnvNames = @(
    "AURA_FREE_AI_PRESET",
    "AURA_OLLAMA_MODELS",
    "AURA_OLLAMA_URL",
    "AURA_AI_ROLES",
    "AURA_AI_OPINIONS_PER_ROLE",
    "AURA_AI_AGENT_TIMEOUT_SECONDS",
    "AURA_MAINTENANCE_AI_PROVIDER",
    "AURA_MAINTENANCE_OLLAMA_MODEL",
    "OPENAI_API_KEY",
    "AURA_OPENAI_MODELS",
    "AURA_MAINTENANCE_OPENAI_MODEL"
)
$SavedTestEnv = @{}
foreach ($Name in $TestEnvNames) {
    $SavedTestEnv[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, $null, "Process")
}

$PytestExit = 0
try {
    Write-Host "Refreshing generated repository-audit evidence..."
    & $VenvPython -m aura.ops.repository_audit
    if ($LASTEXITCODE -ne 0) { throw "Repository audit regeneration failed." }

    & $VenvPython -m aura.ops.repository_audit --check
    if ($LASTEXITCODE -ne 0) { throw "Repository audit verification failed." }

    Write-Host "Running hermetic AURA test suite..."
    & $VenvPython -m pytest -q
    $PytestExit = $LASTEXITCODE
} finally {
    foreach ($Name in $TestEnvNames) {
        [Environment]::SetEnvironmentVariable($Name, $SavedTestEnv[$Name], "Process")
    }
}
if ($PytestExit -ne 0) { throw "AURA tests failed." }

& $VenvPython -m build
if ($LASTEXITCODE -ne 0) { throw "Python distribution build failed." }

& $VenvPython -m aura.ops.final_doctor --profile install --root $Root
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Core setup completed, but production doctor found a missing prerequisite."
}

Write-Host ""
Write-Host "AURA FINAL SETUP COMPLETE" -ForegroundColor Green
Write-Host "1. Double-click CONFIGURE_AURA.cmd and fill only the providers you use."
Write-Host "2. Keep AURA_LIVE_TRADING_ENABLED blank."
Write-Host "3. Open Docker Desktop and MetaTrader 5 DEMO."
Write-Host "4. Double-click START_AURA_PRODUCTION.cmd."
