$ErrorActionPreference = "Stop"

function Read-OptionalPositiveInt {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt
    )

    while ($true) {
        $value = Read-Host $Prompt
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $null
        }

        $parsed = 0
        if ([int]::TryParse($value.Trim(), [ref]$parsed) -and $parsed -gt 0) {
            return $parsed
        }

        Write-Host "Invalid value. Enter a positive whole number, or press Enter to leave it unlimited." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "AURA AI OS - MT5 ALL-MARKET SELF-EVOLVING PAPER RUNNER"
Write-Host "The already logged-in MT5 DEMO session will be reused automatically."
Write-Host "Live MT5 DEMO market data is used. Orders stay inside AURA PaperBroker."
Write-Host "Real-money execution is NOT enabled by this runner."
Write-Host ""

$terminalPath = Read-Host "Optional terminal64.exe full path (press Enter to auto-detect the open MT5)"
$maxSymbols = Read-OptionalPositiveInt "Optional max symbols for first run (recommended 10; Enter = all)"
$maxBatches = Read-OptionalPositiveInt "Optional max closed-candle batches (recommended 20; Enter = continuous)"

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
    if ($null -ne $maxSymbols) {
        $arguments += @("--max-symbols", $maxSymbols.ToString())
    }
    if ($null -ne $maxBatches) {
        $arguments += @("--max-batches", $maxBatches.ToString())
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
