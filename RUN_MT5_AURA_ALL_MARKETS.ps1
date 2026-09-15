$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "AURA AI OS - MT5 ALL-MARKET SELF-EVOLVING PAPER RUNNER"
Write-Host "Live MT5 DEMO market data is used. Orders stay inside AURA PaperBroker."
Write-Host "Real-money execution is NOT enabled by this runner."
Write-Host ""

$login = Read-Host "Enter MT5 DEMO login number"
$server = Read-Host "Enter MT5 DEMO server exactly as shown in MT5"
$terminalPath = Read-Host "Optional terminal64.exe full path (press Enter to auto-detect)"
$securePassword = Read-Host "Enter MT5 DEMO password" -AsSecureString
$maxSymbols = Read-Host "Optional max symbols for first run (recommended 10; Enter = all)"
$maxBatches = Read-Host "Optional max closed-candle batches (recommended 20; Enter = continuous)"

$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    $env:AURA_MT5_DEMO_LOGIN = $login
    $env:AURA_MT5_DEMO_PASSWORD = $plainPassword
    $env:AURA_MT5_DEMO_SERVER = $server
    if ($terminalPath) {
        $env:AURA_MT5_TERMINAL_PATH = $terminalPath
    }

    $arguments = @("-m", "aura.ops.mt5_all_market_runner", "--mode", "learn")
    if ($maxSymbols) {
        $arguments += @("--max-symbols", $maxSymbols)
    }
    if ($maxBatches) {
        $arguments += @("--max-batches", $maxBatches)
    }

    Write-Host ""
    Write-Host "Starting AURA all-market live-data paper/learning runtime..."
    & python @arguments
    exit $LASTEXITCODE
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    Remove-Item Env:AURA_MT5_DEMO_LOGIN -ErrorAction SilentlyContinue
    Remove-Item Env:AURA_MT5_DEMO_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:AURA_MT5_DEMO_SERVER -ErrorAction SilentlyContinue
    Remove-Item Env:AURA_MT5_TERMINAL_PATH -ErrorAction SilentlyContinue
    $plainPassword = $null
    $securePassword = $null
}
