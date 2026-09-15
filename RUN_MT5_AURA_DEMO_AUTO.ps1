$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "AURA AI OS - AUTONOMOUS MT5 DEMO EXECUTION"
Write-Host "DEMO ONLY. Live/real accounts are rejected."
Write-Host "Only scanner/agent/CEO/RiskEngine-approved intents can reach MT5."
Write-Host "Every new broker position receives native SL/TP protection."
Write-Host "Startup is blocked if any MT5 position is already open."
Write-Host ""

$login = Read-Host "Enter MT5 DEMO login number"
$server = Read-Host "Enter MT5 DEMO server exactly as shown in MT5"
$terminalPath = Read-Host "Optional terminal64.exe full path (press Enter to auto-detect)"
$securePassword = Read-Host "Enter MT5 DEMO password" -AsSecureString
$maxSymbols = Read-Host "Max symbols to scan (recommended first run: 10; Enter = 10)"
$maxBatches = Read-Host "Max closed-candle batches (recommended first run: 100; Enter = 100)"
$maxOrders = Read-Host "Maximum actual DEMO broker orders (recommended first run: 3; Enter = 3)"

if (-not $maxSymbols) { $maxSymbols = "10" }
if (-not $maxBatches) { $maxBatches = "100" }
if (-not $maxOrders) { $maxOrders = "3" }

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
    Write-Host "Starting AURA autonomous DEMO execution..."
    python -m aura.ops.mt5_autonomous_demo `
        --max-symbols $maxSymbols `
        --max-batches $maxBatches `
        --max-demo-orders $maxOrders
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
