$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "AURA AI OS - MT5 ALL-MARKET SELF-EVOLVING PAPER RUNNER"
Write-Host "The already logged-in MT5 DEMO session will be reused automatically."
Write-Host "Live MT5 DEMO market data is used. Orders stay inside AURA PaperBroker."
Write-Host "Real-money execution is NOT enabled by this runner."
Write-Host ""

$terminalPath = Read-Host "Optional terminal64.exe full path (press Enter to auto-detect the open MT5)"
$maxSymbols = Read-Host "Optional max symbols for first run (recommended 10; Enter = all)"
$maxBatches = Read-Host "Optional max closed-candle batches (recommended 20; Enter = continuous)"

try {
    Remove-Item Env:AURA_MT5_DEMO_LOGIN -ErrorAction SilentlyContinue
    Remove-Item Env:AURA_MT5_DEMO_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:AURA_MT5_DEMO_SERVER -ErrorAction SilentlyContinue
    if ($terminalPath) {
        $env:AURA_MT5_TERMINAL_PATH = $terminalPath
    }
    else {
        Remove-Item Env:AURA_MT5_TERMINAL_PATH -ErrorAction SilentlyContinue
    }

    $arguments = @("-m", "aura.ops.mt5_all_market_runner", "--mode", "learn")
    if ($maxSymbols) {
        $arguments += @("--max-symbols", $maxSymbols)
    }
    if ($maxBatches) {
        $arguments += @("--max-batches", $maxBatches)
    }

    Write-Host ""
    Write-Host "Starting AURA with the MT5 account currently logged in to the terminal..."
    Write-Host "AURA will stop if the active account is not DEMO or MT5 is disconnected."
    & python @arguments
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:AURA_MT5_TERMINAL_PATH -ErrorAction SilentlyContinue
}
