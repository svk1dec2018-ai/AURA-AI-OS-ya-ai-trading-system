param(
    [ValidateSet("Setup","Start","Doctor","Repair","Configure","Stop")]
    [string]$Action = "Doctor"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Dashboard = Join-Path $Root "dashboard"
$EnvFile = Join-Path $Root ".env.local"

Set-Location $Root
. (Join-Path $PSScriptRoot "aura_env.ps1")

function Invoke-AuraScript([string]$Name) {
    $Path = Join-Path $PSScriptRoot $Name
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Path
    if ($LASTEXITCODE -ne 0) {
        throw ("AURA script failed: " + $Name)
    }
}

function Ensure-PrimeExtras {
    if (-not (Test-Path $VenvPython)) {
        throw "AURA Python environment is missing."
    }
    Write-Host "Installing/verifying AURA Prime free local analytics + ML + observability..."
    & $VenvPython -m pip install --disable-pip-version-check -e ".[dev,distributed,mt5,analytics,ml,observability]"
    if ($LASTEXITCODE -ne 0) {
        throw "AURA Prime optional stack installation failed."
    }
    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency consistency check failed."
    }
}

function Invoke-PrimeDoctor {
    Import-AuraEnv -Path $EnvFile
    & $VenvPython -m aura.ops.final_doctor --profile all-market --root $Root
    $DoctorExit = $LASTEXITCODE
    & $VenvPython -m aura.prime.status
    $PrimeExit = $LASTEXITCODE
    if ($DoctorExit -ne 0 -or $PrimeExit -ne 0) {
        throw "AURA Prime doctor found a blocking software/runtime issue."
    }
}

if ($Action -eq "Setup") {
    Invoke-AuraScript "final_setup_aura.ps1"
    Ensure-PrimeExtras

    Write-Host "Rebuilding dashboard after Prime upgrade..."
    Push-Location $Dashboard
    & npm.cmd install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw "Dashboard dependency install failed."
    }
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw "Dashboard typecheck failed."
    }
    & npm.cmd run build
    $BuildExit = $LASTEXITCODE
    Pop-Location
    if ($BuildExit -ne 0) {
        throw "Dashboard production build failed."
    }

    Write-Host ""
    Write-Host "AURA PRIME SETUP VERIFIED" -ForegroundColor Green
    Write-Host "Configure .env.local, open Docker Desktop + MT5 DEMO, then choose Start."
    exit 0
}

if ($Action -eq "Start") {
    if (-not (Test-Path $VenvPython)) {
        throw "Run AURA Prime Setup first."
    }
    Import-AuraEnv -Path $EnvFile
    if ($env:AURA_LIVE_TRADING_ENABLED -eq "I_UNDERSTAND_AND_APPROVE_LIVE_RISK") {
        throw "AURA Prime default start is paper/DEMO-safe. Clear live-risk acknowledgement first."
    }
    Invoke-AuraScript "start_aura_production.ps1"
    Invoke-PrimeDoctor
    Write-Host "AURA PRIME READY: http://127.0.0.1:3100" -ForegroundColor Green
    exit 0
}

if ($Action -eq "Doctor") {
    if (-not (Test-Path $VenvPython)) {
        throw "AURA is not installed. Choose Setup."
    }
    Invoke-PrimeDoctor
    exit 0
}

if ($Action -eq "Configure") {
    if (-not (Test-Path $EnvFile)) {
        Copy-Item (Join-Path $Root ".env.example") $EnvFile
    }
    Start-Process notepad.exe $EnvFile
    exit 0
}

if ($Action -eq "Stop") {
    Invoke-AuraScript "stop_aura_production.ps1"
    exit 0
}

if ($Action -eq "Repair") {
    Write-Host ""
    Write-Host "AURA PRIME SAFE AUTO-REPAIR" -ForegroundColor Cyan
    Write-Host "Financial/risk source code will not be silently modified." -ForegroundColor DarkGray

    if (-not (Test-Path $VenvPython)) {
        Write-Host "Python environment missing. Re-running setup..." -ForegroundColor Yellow
        Invoke-AuraScript "final_setup_aura.ps1"
    }

    Import-AuraEnv -Path $EnvFile

    & $VenvPython -m pip check *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Repairing Python dependencies..." -ForegroundColor Yellow
        Ensure-PrimeExtras
    }

    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "Node.js missing. Re-running setup..." -ForegroundColor Yellow
        Invoke-AuraScript "final_setup_aura.ps1"
    }

    Push-Location $Dashboard
    & npm.cmd run build *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Repairing dashboard dependencies/build cache..." -ForegroundColor Yellow
        Remove-Item ".next" -Recurse -Force -ErrorAction SilentlyContinue
        & npm.cmd install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            throw "Dashboard dependency repair failed."
        }
        & npm.cmd run build
        $RepairBuild = $LASTEXITCODE
        if ($RepairBuild -ne 0) {
            Pop-Location
            throw "Dashboard build still fails after safe repair."
        }
    }
    Pop-Location

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            $RedisRunning = (& docker ps --filter "name=^/aura-redis$" --format "{{.Names}}")
            if ($RedisRunning -ne "aura-redis") {
                Write-Host "Repairing Redis/fleet runtime..." -ForegroundColor Yellow
                Invoke-AuraScript "start_aura_fleet.ps1"
            }
        } else {
            Write-Warning "Docker Desktop is installed but not running."
        }
    } else {
        Write-Warning "Docker Desktop is missing. Choose Setup to install prerequisites."
    }

    Write-Host "Running credential-free code health probe..."
    & $VenvPython -m aura.maintenance.cli probe --repository $Root
    $ProbeExit = $LASTEXITCODE
    if ($ProbeExit -ne 0) {
        Write-Warning "Source health probe still reports a code issue."
        Write-Host "Use the governed maintenance AI to create a tested proposal; it will not auto-apply:"
        Write-Host "aura-maintenance propose --repository . --component <component> --summary <issue> --source <file>"
    }

    Write-Host "Running Prime status after repairs..."
    & $VenvPython -m aura.prime.status
    Write-Host ""
    Write-Host "SAFE AUTO-REPAIR COMPLETE" -ForegroundColor Green
    exit 0
}
