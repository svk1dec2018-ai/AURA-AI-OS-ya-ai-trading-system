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
echo AURA never asks for your MT5 password in the browser.
echo.

where git >nul 2>&1
if %errorlevel%==0 (
  echo [1/6] Pulling latest AURA main...
  git pull --ff-only origin main
  if errorlevel 1 echo WARNING: git pull failed; using current local files.
) else (
  echo [1/6] Git not found; using current local files.
)

call :detect_python
if not defined AURA_PYTHON goto :python_missing

if not exist ".venv\Scripts\python.exe" (
  echo [2/6] Creating local AURA Python environment...
  %AURA_PYTHON% -m venv .venv
  if errorlevel 1 goto :setup_failed
)
set "AURA_PYTHON=.venv\Scripts\python.exe"

echo [3/6] Synchronizing AURA + official MetaTrader5 bridge...
"%AURA_PYTHON%" -m pip install --disable-pip-version-check -e ".[mt5]"
if errorlevel 1 goto :setup_failed

echo [4/6] Verifying MetaTrader5 Python bridge...
"%AURA_PYTHON%" -c "import MetaTrader5 as mt5; print('MetaTrader5 bridge ready:', getattr(mt5,'__version__','installed'))"
if errorlevel 1 goto :mt5_bridge_failed

echo [5/6] Releasing clean local AURA port 8766...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8766 .*LISTENING"') do taskkill /PID %%P /F >nul 2>&1
timeout /t 1 /nobreak >nul

echo [6/6] Starting fresh MT5-preflight Command Center...
echo.
echo AURA URL:       http://127.0.0.1:8766
echo MT5 API check:  http://127.0.0.1:8766/api/mt5/preflight
echo Keep this window open while using AURA.
echo.
start "" "http://127.0.0.1:8766/?fresh=1"
"%AURA_PYTHON%" -m aura.webapp.server_v3 --port 8766
set "AURA_EXIT=%errorlevel%"

echo.
echo AURA stopped with exit code %AURA_EXIT%.
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

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "AURA_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined AURA_PYTHON exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "AURA_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined AURA_PYTHON exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "AURA_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined AURA_PYTHON exit /b 0

where winget >nul 2>&1
if !errorlevel!==0 (
  echo Python 3.11+ not found. Installing free Python 3.11...
  winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements --silent
  py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
  if !errorlevel!==0 set "AURA_PYTHON=py -3.11"
)
exit /b 0

:python_missing
echo.
echo ERROR: Python 3.11 or newer could not be started.
echo Install Python 3.11+ and run START_AURA_AI_OS.cmd again.
pause
exit /b 1

:mt5_bridge_failed
echo.
echo ERROR: Official MetaTrader5 Python bridge could not be imported.
echo Keep internet available and run this launcher again.
pause
exit /b 1

:setup_failed
echo.
echo ERROR: AURA setup failed. Check the message above and retry.
pause
exit /b 1
