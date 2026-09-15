$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "AURA AI OS - GENERIC PROTECTED MT5 DEMO TRADE"
Write-Host "DEMO accounts only. Live accounts are rejected by AURA."
Write-Host "Native SL/TP is attached before order submission."
Write-Host "Default behavior auto-closes the AURA position after 30 seconds."
Write-Host ""

$login = Read-Host "Enter MT5 DEMO login number"
$server = Read-Host "Enter MT5 DEMO server exactly as shown in MT5"
$terminalPath = Read-Host "Optional terminal64.exe full path (press Enter to auto-detect)"
$securePassword = Read-Host "Enter MT5 DEMO password" -AsSecureString
$symbol = Read-Host "Symbol to trade (example XAUUSD, EURUSD, BTCUSD)"
$side = (Read-Host "Side BUY or SELL").ToUpperInvariant()
$volume = Read-Host "Optional volume (Enter = broker minimum)"
$keepOpen = (Read-Host "Keep protected DEMO position open? type YES, otherwise it auto-closes after 30 sec").ToUpperInvariant()

if ($side -ne "BUY" -and $side -ne "SELL") {
    throw "Side must be BUY or SELL"
}

$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    $env:AURA_MT5_DEMO_LOGIN = $login
    $env:AURA_MT5_DEMO_PASSWORD = $plainPassword
    $env:AURA_MT5_DEMO_SERVER = $server
    if ($terminalPath) {
        $env:AURA_MT5_TERMINAL_PATH = $terminalPath
    }

    $arguments = @(
        "-m", "aura.ops.mt5_demo_trade",
        "--symbol", $symbol,
        "--side", $side
    )
    if ($volume) {
        $arguments += @("--volume", $volume)
    }
    if ($keepOpen -eq "YES") {
        $arguments += "--keep-open"
    }

    Write-Host ""
    Write-Host "Submitting protected DEMO-only trade through AURA..."
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
