$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Runtime = Join-Path $Root "runtime\fleet"
$SupervisorPid = Join-Path $Runtime "supervisor.pid"
$RedisName = "aura-redis"
$RedisUrl = "redis://127.0.0.1:6379/0"

Set-Location $Root
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AURA Distributed Fleet - Nexus-style runtime" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) { throw "AURA .venv was not found. Run START_AURA2.cmd once first." }

Write-Host "Installing/updating AURA distributed dependency..."
& $VenvPython -m pip install --disable-pip-version-check -e ".[distributed]"
if ($LASTEXITCODE -ne 0) { throw "Distributed AURA dependency install failed." }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required for the one-click Redis fleet. Install Docker Desktop, open it, then run START_AURA_FLEET.cmd again."
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker is installed but the Docker engine is not running. Open Docker Desktop and wait until it is ready." }

$Exists = (& docker ps -a --filter "name=^/$RedisName$" --format "{{.Names}}")
if ($Exists -eq $RedisName) {
    $Running = (& docker inspect -f "{{.State.Running}}" $RedisName)
    if ($Running -ne "true") {
        Write-Host "Starting existing AURA Redis container..."
        & docker start $RedisName | Out-Null
    } else {
        Write-Host "AURA Redis is already running."
    }
} else {
    Write-Host "Creating AURA Redis 7 container..."
    & docker run -d --name $RedisName -p 6379:6379 --restart unless-stopped redis:7-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not start the AURA Redis container." }
}

$env:AURA_REDIS_URL = $RedisUrl
for ($i = 0; $i -lt 30; $i++) {
    & $VenvPython -m aura.fleet.cli --check-redis *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Milliseconds 500
}
& $VenvPython -m aura.fleet.cli --check-redis
if ($LASTEXITCODE -ne 0) { throw "Redis started but AURA could not connect to it." }

if (Test-Path $SupervisorPid) {
    $SavedPid = Get-Content $SupervisorPid | Select-Object -First 1
    if ($SavedPid -match "^[0-9]+$") {
        $Existing = Get-Process -Id ([int]$SavedPid) -ErrorAction SilentlyContinue
        if ($Existing) {
            Write-Host ("AURA Fleet supervisor is already running: PID " + $SavedPid)
            exit 0
        }
    }
    Remove-Item $SupervisorPid -Force -ErrorAction SilentlyContinue
}

$OutLog = Join-Path $Runtime "supervisor.out.log"
$ErrLog = Join-Path $Runtime "supervisor.err.log"
Write-Host "Starting nine AURA fleet services..."
$Supervisor = Start-Process -FilePath $VenvPython -ArgumentList @("-m","aura.fleet.process_supervisor","--redis-url",$RedisUrl,"--runtime-dir",$Runtime) -WorkingDirectory $Root -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
Set-Content -Path $SupervisorPid -Value $Supervisor.Id

Start-Sleep -Seconds 3
if ($Supervisor.HasExited) { throw "AURA Fleet supervisor exited during startup. Check runtime\fleet\supervisor.err.log." }

Write-Host ""
Write-Host "AURA FLEET READY" -ForegroundColor Green
Write-Host ("Supervisor PID: " + $Supervisor.Id) -ForegroundColor Green
Write-Host "Redis:          127.0.0.1:6379" -ForegroundColor Green
Write-Host "Services:       9100-9108" -ForegroundColor Green
Write-Host ""
Write-Host "Open AURA 2 > Distributed Fleet to see live SSE heartbeats."
Write-Host "No API keys are required for fleet infrastructure itself."
