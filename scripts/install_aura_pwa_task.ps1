param([switch]$StartNow)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Set up the repository Python environment first.' }
$taskName = 'AURA Owner PWA'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'AURA Owner PWA task already exists; inspect it before updating.'
}
$action = New-ScheduledTaskAction -Execute $pythonPath -WorkingDirectory $repoRoot -Argument '-m aura.webapp.server_v3 --port 8766 --auto-start-demo --auto-start-batches 0'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Local AURA owner app and continuous protected DEMO runtime. Requires logged-in MT5 terminal.' | Out-Null
if ($StartNow) { Start-ScheduledTask -TaskName $taskName }
Write-Output 'AURA Owner PWA installed for Windows logon; app recovery enabled. MT5 must remain open.'
