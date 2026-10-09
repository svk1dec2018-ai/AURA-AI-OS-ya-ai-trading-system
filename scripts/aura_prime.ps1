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
    & $VenvPython -m pip install --disable-pip-version-check -e ".[dev,mt5,analytics,observability]"
    if ($LASTEXITCODE -ne 0) {
        throw "AURA Prime optional stack installation failed."
    }
    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency consistency check failed."
    }
}

function Invoke-PrimeDoctor([string]$Profile = "prime-local") {
    Import-AuraEnv -Path $EnvFile
    & $VenvPython -m aura.ops.final_doctor --profile $Profile --root $Root
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
    & npm.cmd ci --no-audit --no-fund
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
    Write-Host "Configure .env.local, open MT5 DEMO, then choose Start. Docker/ML extras are optional."
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
    Write-Host "Starting AURA Prime local control plane..."
    Invoke-AuraScript "start_aura2_dashboard.ps1"

    if ($env:AURA_PRIME_DISTRIBUTED -eq "1") {
        Write-Host "Distributed mode requested; starting Redis fleet..."
        Invoke-AuraScript "start_aura_fleet.ps1"
    } else {
        Write-Host "Distributed Redis fleet: optional/off" -ForegroundColor DarkGray
    }

    Invoke-PrimeDoctor "prime-ui"
    Write-Host "AURA PRIME READY: http://127.0.0.1:3100" -ForegroundColor Green
    Write-Host "Dashboard is ready. DEMO trading still requires a connected DEMO account and broker checks."
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
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "aura_prime_configure.ps1") -EnvPath $EnvFile
    if ($LASTEXITCODE -ne 0) {
        throw "AURA Prime credential wizard failed."
    }
    exit 0
}

if ($Action -eq "Stop") {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_aura_fleet.ps1")
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_aura2_dashboard.ps1")
    Write-Host "AURA Prime stopped. MetaTrader 5 was left open." -ForegroundColor Green
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
        & npm.cmd ci --no-audit --no-fund
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

    if ($env:AURA_PRIME_DISTRIBUTED -eq "1" -and (Get-Command docker -ErrorAction SilentlyContinue)) {
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
    } elseif ($env:AURA_PRIME_DISTRIBUTED -eq "1") {
        Write-Warning "Distributed mode requested; Docker Desktop is missing."
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
    if ($LASTEXITCODE -ne 0 -or $ProbeExit -ne 0) {
        throw "Repair checks did not pass. Review the diagnostics above."
    }
    Write-Host ""
    Write-Host "SAFE AUTO-REPAIR COMPLETE" -ForegroundColor Green
    exit 0
}
