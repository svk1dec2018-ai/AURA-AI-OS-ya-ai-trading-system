$ErrorActionPreference = "Continue"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root "runtime\aura2_dashboard"

foreach ($name in @("dashboard","backend")) {
    $pidFile = Join-Path $Runtime ($name + ".pid")
    if (Test-Path $pidFile) {
        $savedPid = Get-Content $pidFile | Select-Object -First 1
        if ($savedPid -match "^[0-9]+$") {
            $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $savedPid) -ErrorAction SilentlyContinue
            if ($process -and [string]$process.CommandLine -match [regex]::Escape($Root)) {
                Write-Host ("Stopping AURA " + $name + " process tree PID " + $savedPid)
                taskkill /PID $savedPid /T /F | Out-Null
            } else {
                Write-Warning ("Skipping unverified/stale PID " + $savedPid)
            }
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "AURA 2 dashboard services stopped. MetaTrader 5 was not closed."
