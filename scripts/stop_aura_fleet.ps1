$ErrorActionPreference = "Continue"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root "runtime\fleet"
$SupervisorPid = Join-Path $Runtime "supervisor.pid"

if (Test-Path $SupervisorPid) {
    $SavedPid = Get-Content $SupervisorPid | Select-Object -First 1
    if ($SavedPid -match "^[0-9]+$") {
        Write-Host ("Stopping AURA Fleet supervisor tree PID " + $SavedPid)
        taskkill /PID $SavedPid /T /F | Out-Null
    }
    Remove-Item $SupervisorPid -Force -ErrorAction SilentlyContinue
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $Running = (& docker ps --filter "name=^/aura-redis$" --format "{{.Names}}")
    if ($Running -eq "aura-redis") {
        Write-Host "Stopping AURA Redis..."
        & docker stop aura-redis | Out-Null
    }
}

Write-Host "AURA distributed fleet stopped. MT5 and the AURA dashboard were not closed."
