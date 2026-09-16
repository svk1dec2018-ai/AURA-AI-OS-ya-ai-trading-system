$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "AURA AI OS - SELF-EVOLVING AUTONOMOUS MT5 DEMO"
Write-Host "DEMO ONLY. Live/real accounts are rejected."
Write-Host "AURA scans broker-exposed tradable markets, runs agents/CEO/RiskEngine,"
Write-Host "learns from forward outcomes, and only approved orders can reach MT5 DEMO."
Write-Host "Every new position receives broker-native SL/TP protection."
Write-Host "Pyramiding is blocked; fund transfer/withdrawal capability is not present."
Write-Host "Do NOT paste your MT5 password into ChatGPT, GitHub, screenshots, or source files."
Write-Host ""

$login = Read-Host "Enter MT5 DEMO login number"
$server = Read-Host "Enter MT5 DEMO server exactly as shown in MT5"
$terminalPath = Read-Host "Optional terminal64.exe full path (press Enter to auto-detect)"
$securePassword = Read-Host "Enter MT5 DEMO password" -AsSecureString
$maxSymbols = Read-Host "Max symbols to scan (recommended first run: 10; Enter = 10)"
$maxBatches = Read-Host "Max closed-candle batches (recommended first run: 100; Enter = 100)"

if (-not $maxSymbols) { $maxSymbols = "10" }
if (-not $maxBatches) { $maxBatches = "100" }

$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    $env:AURA_MT5_DEMO_LOGIN = $login
    $env:AURA_MT5_DEMO_PASSWORD = $plainPassword
    $env:AURA_MT5_DEMO_SERVER = $server
    if ($terminalPath) {
        $env:AURA_MT5_TERMINAL_PATH = $terminalPath
    }

    Write-Host ""
    Write-Host "Starting AURA autonomous self-evolving DEMO execution..."
    Write-Host "Default risk caps: order 0.50%, gross 10%, symbol 2%, daily loss 3%, drawdown 8%."
    Write-Host "Default native protection: SL 35 bps, TP 70 bps."
    Write-Host ""

    python -m aura.ops.mt5_autonomous_demo `
        --max-symbols $maxSymbols `
        --max-batches $maxBatches
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
