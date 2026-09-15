$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "AURA AI OS - MT5 XAUUSD DEMO Readiness Check"
Write-Host "This script does NOT place any trade/order."
Write-Host "Credentials are used only in this PowerShell process and are cleared afterwards."
Write-Host ""

$login = Read-Host "Enter MT5 DEMO login number"
$server = Read-Host "Enter MT5 DEMO server exactly as shown in MT5"
$terminalPath = Read-Host "Optional MT5 terminal64.exe full path (press Enter to auto-detect)"
$securePassword = Read-Host "Enter MT5 DEMO password" -AsSecureString

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
    Write-Host "Running read-only/no-order readiness checks..."
    python -m aura.ops.mt5_demo_readiness
    $exitCode = $LASTEXITCODE

    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "READY: MT5 DEMO + XAUUSD market-data path passed all checks."
    }
    else {
        Write-Host "NOT READY: Read the failed check above. No order was placed."
    }
    exit $exitCode
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
