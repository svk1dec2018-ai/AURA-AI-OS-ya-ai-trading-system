Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "              AURA AI OS - DEV AUTOPILOT" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Existing repo only. Protected MT5 DEMO safety constraints remain active."
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: git is not available in PATH." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Claude Code CLI was not found." -ForegroundColor Red
    Write-Host "Open the terminal/profile where your Claude + OmniRoute setup works and run this script there."
    exit 1
}

$promptPath = Join-Path $PSScriptRoot "AURA_AUTOPILOT_PROMPT.md"
if (-not (Test-Path $promptPath)) {
    Write-Host "ERROR: AURA_AUTOPILOT_PROMPT.md is missing." -ForegroundColor Red
    exit 1
}

$logDir = Join-Path $PSScriptRoot "runtime\dev_autopilot"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "autopilot-$stamp.log"

Write-Host "[1/4] Repository status"
git status --short

Write-Host ""
Write-Host "[2/4] Pulling latest main when fast-forward is safe"
try {
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: git pull did not complete. Autopilot will inspect the current tree and must not overwrite local work." -ForegroundColor Yellow
    }
} catch {
    Write-Host "WARNING: git pull failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[3/4] Starting Claude Code autonomous engineering loop"
Write-Host "Log: $logPath"
Write-Host "The run may edit files, run tests and create normal git commits. Destructive git operations are forbidden by the master prompt."
Write-Host ""

$prompt = Get-Content -Raw -Path $promptPath

$allowedTools = "Bash,Read,Edit"
$disallowedTools = "Bash(git reset --hard *),Bash(git clean *),Bash(git push --force *),Bash(git push -f *),Bash(rm -rf *),Bash(del /s /q *)"

& claude -p $prompt `
    --permission-mode acceptEdits `
    --allowedTools $allowedTools `
    --disallowedTools $disallowedTools `
    --max-turns 80 `
    --output-format text 2>&1 | Tee-Object -FilePath $logPath

$claudeExit = $LASTEXITCODE

Write-Host ""
Write-Host "[4/4] Final repository status"
git status --short
Write-Host ""
if ($claudeExit -eq 0) {
    Write-Host "AURA DEV AUTOPILOT finished this run normally." -ForegroundColor Green
} else {
    Write-Host "AURA DEV AUTOPILOT stopped with exit code $claudeExit." -ForegroundColor Yellow
    Write-Host "Read the log above. A blocked external dependency should be recorded in AURA_BLOCKERS.md by the agent."
}
Write-Host "Log saved to: $logPath"
exit $claudeExit
