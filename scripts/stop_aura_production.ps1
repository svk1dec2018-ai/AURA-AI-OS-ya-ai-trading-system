$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Write-Host "Stopping AURA distributed fleet..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_aura_fleet.ps1")
Write-Host "Stopping AURA dashboard/backend..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "stop_aura2_dashboard.ps1")
Write-Host "AURA stopped."
