@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AURA AI OS - Owner Command Center

cls
echo ============================================================
echo                 AURA AI OS - ONE CLICK START
echo ============================================================
echo.
echo Protected MT5 DEMO / research mode.
echo Keep MetaTrader 5 open and logged into your DEMO account.
echo The AURA web app will never ask for your MT5 password.
echo.

where git >nul 2>&1
if %errorlevel%==0 (
  echo [1/6] Checking latest AURA main branch...
  git pull --ff-only origin main
  if errorlevel 1 (
    echo.
    echo WARNING: Git fast-forward update was not completed.
    echo AURA will continue with the local files already on this PC.
    echo.
  )
) else (
  echo [1/6] Git not found - using current local AURA files.
)

call :detect_python
if not defined AURA_PYTHON (
  echo.
  echo Python 3.11 or newer was not detected.
  where winget >nul 2>&1
  if %errorlevel%==0 (
    echo [2/6] Installing free Python 3.11 automatically with Windows Package Manager...
    winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements --silent
    if errorlevel 1 goto :python_missing
    call :detect_python
  )
)

if not defined AURA_PYTHON goto :python_missing

if not exist ".venv\Scripts\python.exe" (
  echo [2/6] Creating local AURA Python environment...
  %AURA_PYTHON% -m venv .venv
  if errorlevel 1 goto :setup_failed
  set "AURA_PYTHON=.venv\Scripts\python.exe"
) else (
  echo [2/6] Local Python environment ready.
  set "AURA_PYTHON=.venv\Scripts\python.exe"
)

echo [3/6] Synchronizing AURA and official MetaTrader5 bridge...
"%AURA_PYTHON%" -m pip install --disable-pip-version-check -e ".[mt5]"
if errorlevel 1 goto :setup_failed

echo [4/6] Verifying MetaTrader5 Python bridge...
"%AURA_PYTHON%" -c "import MetaTrader5 as mt5; print('MetaTrader5 bridge ready:', getattr(mt5, '__version__', 'installed'))"
if errorlevel 1 goto :mt5_bridge_failed

echo [5/6] Closing any stale AURA web server on port 8765...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$connections=Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; foreach($c in $connections){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess) -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match 'aura\.webapp\.server(_v3)?'){Write-Host ('Stopping stale AURA server PID '+$p.ProcessId); Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue}}" >nul 2>&1
timeout /t 1 /nobreak >nul

echo [6/6] Opening AURA AI OS with MT5 preflight...
echo.
echo Browser address: http://127.0.0.1:8765
echo Keep this window open while using AURA.
echo The Command Center will show MT5 DEMO connection and live broker symbols.
echo.
"%AURA_PYTHON%" -m aura.webapp.server_v3 --open
set "AURA_EXIT=%errorlevel%"

echo.
if not "%AURA_EXIT%"=="0" (
  echo AURA exited with code %AURA_EXIT%.
  echo If port 8765 is still in use, close every old AURA black CMD window and run this launcher again.
  echo Otherwise check the message above and retry.
) else (
  echo AURA stopped normally.
)
pause
exit /b %AURA_EXIT%

:detect_python
set "AURA_PYTHON="
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
  if !errorlevel!==0 set "AURA_PYTHON=.venv\Scripts\python.exe"
)
if defined AURA_PYTHON exit /b 0

py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if !errorlevel!==0 set "AURA_PYTHON=py -3.11"
if defined AURA_PYTHON exit /b 0

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if !errorlevel!==0 set "AURA_PYTHON=py -3"
if defined AURA_PYTHON exit /b 0

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if !errorlevel!==0 set "AURA_PYTHON=python"
if defined AURA_PYTHON exit /b 0

python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if !errorlevel!==0 set "AURA_PYTHON=python3"
if defined AURA_PYTHON exit /b 0

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "AURA_PYTHON=^"%LOCALAPPDATA%\Programs\Python\Python313\python.exe^""
if defined AURA_PYTHON exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "AURA_PYTHON=^"%LOCALAPPDATA%\Programs\Python\Python312\python.exe^""
if defined AURA_PYTHON exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "AURA_PYTHON=^"%LOCALAPPDATA%\Programs\Python\Python311\python.exe^""
if defined AURA_PYTHON exit /b 0

if exist "%ProgramFiles%\Python313\python.exe" set "AURA_PYTHON=^"%ProgramFiles%\Python313\python.exe^""
if defined AURA_PYTHON exit /b 0
if exist "%ProgramFiles%\Python312\python.exe" set "AURA_PYTHON=^"%ProgramFiles%\Python312\python.exe^""
if defined AURA_PYTHON exit /b 0
if exist "%ProgramFiles%\Python311\python.exe" set "AURA_PYTHON=^"%ProgramFiles%\Python\Python311\python.exe^""
exit /b 0

:python_missing
echo.
echo ERROR: Working Python 3.11 or newer could not be started.
echo Install Python 3.11+ from the Microsoft Store or python.org, then run this file again.
pause
exit /b 1

:mt5_bridge_failed
echo.
echo ERROR: The official MetaTrader5 Python bridge could not be installed or imported.
echo Make sure Windows is online, then run this launcher again.
echo.
pause
exit /b 1

:setup_failed
echo.
echo ERROR: AURA setup could not be completed automatically.
echo Check the message above and run this launcher again.
pause
exit /b 1