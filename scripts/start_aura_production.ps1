$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Root ".env.local"

Set-Location $Root
. (Join-Path $PSScriptRoot "aura_env.ps1")
Import-AuraEnv -Path $EnvFile

if (-not (Test-Path $VenvPython)) {
    throw "AURA is not installed. Run FINAL_SETUP_AURA.cmd first."
}

$liveAck = [Environment]::GetEnvironmentVariable("AURA_LIVE_TRADING_ENABLED", "Process")
if ($liveAck -eq "I_UNDERSTAND_AND_APPROVE_LIVE_RISK") {
    throw "Production starter is demo/paper-safe by default. Clear AURA_LIVE_TRADING_ENABLED before starting."
}

Write-Host "Starting AURA 2 dashboard/backend first so diagnostics are always available..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start_aura2_dashboard.ps1")
if ($LASTEXITCODE -ne 0) { throw "AURA dashboard/backend failed to start." }

$FleetReady = $true
$FleetError = ""
try {
    Write-Host "Starting AURA distributed fleet..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start_aura_fleet.ps1")
    if ($LASTEXITCODE -ne 0) {
        $FleetReady = $false
        $FleetError = "Fleet launcher returned exit code " + $LASTEXITCODE
    }
} catch {
    $FleetReady = $false
    $FleetError = $_.Exception.Message
}

if (-not $FleetReady) {
    Write-Warning ("AURA dashboard is running, but distributed fleet is DEGRADED: " + $FleetError)
    Write-Warning "Open AURA > System Health / Distributed Fleet after Docker is ready, then run START_AURA_FLEET.cmd."
}

Import-AuraEnv -Path $EnvFile
& $VenvPython -m aura.ops.final_doctor --profile all-market --root $Root
$DoctorExit = $LASTEXITCODE

Write-Host ""
if ($DoctorExit -eq 0 -and $FleetReady) {
    Write-Host "AURA PRODUCTION PAPER/DEMO STACK READY" -ForegroundColor Green
} else {
    Write-Host "AURA STARTED IN DIAGNOSTIC / DEGRADED MODE" -ForegroundColor Yellow
    Write-Host "The dashboard remains available so you can see and fix the exact external dependency." -ForegroundColor Yellow
}
Write-Host "Dashboard: http://127.0.0.1:3100" -ForegroundColor Green
Write-Host "Backend:   http://127.0.0.1:8766" -ForegroundColor Green
Write-Host "Live money remains locked until broker evidence phases 11 and 15 pass."
