$ErrorActionPreference = "Continue"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root "runtime\aura2_dashboard"

foreach ($name in @("dashboard","backend")) {
    $pidFile = Join-Path $Runtime ($name + ".pid")
    if (Test-Path $pidFile) {
        $savedPid = Get-Content $pidFile | Select-Object -First 1
        if ($savedPid -match "^[0-9]+$") {
            Write-Host ("Stopping AURA 2 " + $name + " process tree PID " + $savedPid)
            taskkill /PID $savedPid /T /F | Out-Null
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "AURA 2 dashboard services stopped. MetaTrader 5 was not closed."
