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

Write-Host "Starting AURA distributed fleet..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start_aura_fleet.ps1")
if ($LASTEXITCODE -ne 0) { throw "AURA fleet failed to start." }

Write-Host "Starting AURA 2 dashboard/backend..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start_aura2_dashboard.ps1")
if ($LASTEXITCODE -ne 0) { throw "AURA dashboard/backend failed to start." }

Import-AuraEnv -Path $EnvFile
& $VenvPython -m aura.ops.final_doctor --profile running --root $Root
if ($LASTEXITCODE -ne 0) { throw "AURA started but final production doctor found a blocking issue." }

Write-Host ""
Write-Host "AURA PRODUCTION PAPER/DEMO STACK READY" -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:3100" -ForegroundColor Green
Write-Host "Live money remains locked until broker evidence phases 11 and 15 pass."
