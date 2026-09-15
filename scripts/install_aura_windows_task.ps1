param(
    [string]$TaskName = "AURA AI OS Paper Research",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$launcher = Join-Path $repoRoot "scripts\start_aura_ollama.ps1"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $launcher)) {
    throw "AURA launcher not found: $launcher"
}
if (-not (Test-Path $python)) {
    throw "Run START_AURA_OLLAMA.cmd once before installing the background task."
}

& $python (Join-Path $repoRoot "examples\run_production_preflight.py") --mode paper --connector public
if ($LASTEXITCODE -ne 0) {
    throw "AURA paper preflight failed; background task was not installed."
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $launcher + '"'),
    "-NoVoice",
    "-SkipDependencyInstall"
) -join " "
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "AURA public-data Multi-AI paper research. Real money is disabled." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName" -ForegroundColor Green
Write-Host "Live money remains disabled. State is stored under runtime\free_public_autonomy." -ForegroundColor Yellow
if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "AURA background task started." -ForegroundColor Green
}
