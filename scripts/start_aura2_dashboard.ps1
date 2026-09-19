$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root "runtime\aura2_dashboard"
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Dashboard = Join-Path $Root "dashboard"

Set-Location $Root
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

function Test-Url([string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Test-AuraHealth([string]$Url) {
    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
        return $response.ok -eq $true
    } catch {
        return $false
    }
}

function Stop-StaleDashboardListener {
    try {
        $listeners = Get-NetTCPConnection -LocalPort 3100 -State Listen -ErrorAction Stop
    } catch {
        return
    }
    foreach ($listener in $listeners) {
        $ownerPid = [int]$listener.OwningProcess
        try {
            $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $ownerPid)
            $command = [string]$process.CommandLine
            if ($command -match "next|node|npm") {
                Write-Host ("Stopping stale AURA dashboard listener PID " + $ownerPid + " on port 3100...") -ForegroundColor Yellow
                taskkill /PID $ownerPid /T /F | Out-Null
            }
        } catch {}
    }
}

function New-AuraVenv {
    if (Test-Path $VenvPython) { return }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & py -3.12 -m venv $VenvDir
            return
        }
        & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & py -3.11 -m venv $VenvDir
            return
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & python -m venv $VenvDir
            return
        }
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Python 3.12 not found. Installing it once..." -ForegroundColor Yellow
        winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.12 -m venv $VenvDir
            return
        }
    }

    throw "Python 3.11+ is required. Install Python 3.12 and run START_AURA2.cmd again."
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AURA 2 - AI Trading Control Room" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

New-AuraVenv
if (-not (Test-Path $VenvPython)) { throw "AURA Python environment could not be created." }

# Repair interrupted pip upgrades such as "~ip" / "~ip-*.dist-info" leftovers.
$SitePackages = & $VenvPython -c "import site; print(site.getsitepackages()[0])"
if ($SitePackages -and (Test-Path $SitePackages)) {
    Get-ChildItem -LiteralPath $SitePackages -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "~ip*" } |
        ForEach-Object {
            Write-Host ("Removing broken pip leftover: " + $_.Name) -ForegroundColor Yellow
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
}

Write-Host "Installing/updating AURA backend and official MT5 bridge..."
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
& $VenvPython -m pip install --disable-pip-version-check -e ".[mt5]"
if ($LASTEXITCODE -ne 0) { throw "AURA Python package setup failed." }
& $VenvPython -c "import MetaTrader5; print('MetaTrader5 bridge ready')"
if ($LASTEXITCODE -ne 0) { throw "MetaTrader5 Python bridge could not be imported." }

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Node.js not found. Installing Node.js LTS once..." -ForegroundColor Yellow
        winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
        $env:Path = "C:\Program Files\nodejs;" + $env:Path
    } else {
        throw "Node.js 20+ is required. Install Node.js LTS and run START_AURA2.cmd again."
    }
}

$NodeMajor = [int](& node -p "process.versions.node.split('.')[0]")
if ($NodeMajor -lt 20) { throw "Node.js 20 or newer is required." }

if (-not (Test-Path (Join-Path $Dashboard "node_modules\next"))) {
    Write-Host "Installing AURA 2 dashboard packages. This happens on the first run..."
    Push-Location $Dashboard
    & npm.cmd install --no-audit --no-fund
    $NpmExit = $LASTEXITCODE
    Pop-Location
    if ($NpmExit -ne 0) { throw "Dashboard npm install failed." }
}

$env:AURA_BACKEND_URL = "http://127.0.0.1:8766"
Write-Host "Building current AURA 2 dashboard for production..."
Push-Location $Dashboard
& npm.cmd run build
$BuildExit = $LASTEXITCODE
Pop-Location
if ($BuildExit -ne 0) { throw "AURA 2 dashboard production build failed." }

if (-not (Test-Url "http://127.0.0.1:8766/api/health")) {
    Write-Host "Starting AURA backend on http://127.0.0.1:8766 ..."
    $backend = Start-Process -FilePath $VenvPython -ArgumentList @("-m","aura.webapp.server_v3","--port","8766") -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $Runtime "backend.out.log") -RedirectStandardError (Join-Path $Runtime "backend.err.log") -PassThru
    Set-Content -Path (Join-Path $Runtime "backend.pid") -Value $backend.Id

    for ($i = 0; $i -lt 40; $i++) {
        if (Test-Url "http://127.0.0.1:8766/api/health") { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Url "http://127.0.0.1:8766/api/health")) {
        throw "Backend did not start. Open runtime\aura2_dashboard\backend.err.log."
    }
} else {
    Write-Host "AURA backend is already running."
}

$DashboardRootOk = Test-Url "http://127.0.0.1:3100"
$DashboardProxyOk = Test-AuraHealth "http://127.0.0.1:3100/api/health"

if ($DashboardRootOk -and -not $DashboardProxyOk) {
    Write-Host "A dashboard is listening on port 3100 but its AURA API proxy is broken/stale." -ForegroundColor Yellow
    Stop-StaleDashboardListener
    Start-Sleep -Milliseconds 700
    $DashboardRootOk = $false
    $DashboardProxyOk = $false
}

if (-not $DashboardRootOk) {
    Write-Host "Starting premium production dashboard on http://127.0.0.1:3100 ..."
    $dash = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c","set AURA_BACKEND_URL=http://127.0.0.1:8766&& npm.cmd run start") -WorkingDirectory $Dashboard -RedirectStandardOutput (Join-Path $Runtime "dashboard.out.log") -RedirectStandardError (Join-Path $Runtime "dashboard.err.log") -PassThru
    Set-Content -Path (Join-Path $Runtime "dashboard.pid") -Value $dash.Id

    for ($i = 0; $i -lt 80; $i++) {
        if ((Test-Url "http://127.0.0.1:3100") -and (Test-AuraHealth "http://127.0.0.1:3100/api/health")) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Url "http://127.0.0.1:3100")) {
        throw "Dashboard did not start. Open runtime\aura2_dashboard\dashboard.err.log."
    }
    if (-not (Test-AuraHealth "http://127.0.0.1:3100/api/health")) {
        throw "Dashboard opened but its backend proxy is unhealthy. Check dashboard.err.log and backend.err.log."
    }
} else {
    Write-Host "AURA 2 dashboard is already running and its backend proxy is healthy."
}

Write-Host ""
Write-Host "AURA 2 READY" -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:3100" -ForegroundColor Green
Write-Host "Backend:   http://127.0.0.1:8766" -ForegroundColor Green
Write-Host "Proxy:     VERIFIED" -ForegroundColor Green
Write-Host ""
Write-Host "Keep MetaTrader 5 open and logged in to a DEMO account."
Write-Host "This launcher does not auto-start trading. Use Start AURA DEMO inside the dashboard."
Start-Process "http://127.0.0.1:3100"
