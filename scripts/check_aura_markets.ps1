$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run AURA_PRIME.cmd option 1 Setup first." }
. (Join-Path $PSScriptRoot "aura_env.ps1")
Import-AuraEnv -Path (Join-Path $Root ".env.local")
Write-Host "Read-only full MT5 DEMO market inventory. No orders will be sent."
& $Python -m aura.ops.mt5_market_inventory
if ($LASTEXITCODE -ne 0) { throw "Market inventory failed. Open MT5 DEMO and check credentials/path." }
Write-Host "Saved runtime\mt5_market_inventory.json. Metadata discovery is not execution certification."
