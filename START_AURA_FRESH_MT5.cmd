@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AURA AI OS - Fresh MT5 DEMO Start

cls
echo ============================================================
echo          AURA AI OS - FRESH MT5 DEMO START
echo ============================================================
echo.
echo This launcher uses fresh local port 8766 to bypass any old
 echo AURA server/service-worker still cached on port 8765.
echo Keep MetaTrader 5 open and logged in to a DEMO account.
echo.

where git >nul 2>&1
if %errorlevel%==0 (
  echo [1/5] Pulling latest AURA main...
  git pull --ff-only origin main
  if errorlevel 1 (
    echo WARNING: git pull failed. Continuing with current local files.
  )
) else (
  echo [1/5] Git not found. Continuing with current local files.
)

if not exist ".venv\Scripts\python.exe" (
  echo [2/5] Creating local Python environment...
  py -3.11 -m venv .venv
  if errorlevel 1 goto :setup_failed
) else (
  echo [2/5] Local Python environment ready.
)

set "AURA_PYTHON=.venv\Scripts\python.exe"

echo [3/5] Installing/synchronizing AURA + official MetaTrader5 bridge...
"%AURA_PYTHON%" -m pip install --disable-pip-version-check -e ".[mt5]"
if errorlevel 1 goto :setup_failed

"%AURA_PYTHON%" -c "import MetaTrader5 as mt5; print('MetaTrader5 bridge ready:', getattr(mt5,'__version__','installed'))"
if errorlevel 1 goto :mt5_failed

echo [4/5] Releasing fresh AURA port 8766 if needed...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8766 .*LISTENING"') do (
  taskkill /PID %%P /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [5/5] Starting AURA MT5-preflight server on fresh origin...
echo.
echo Fresh AURA URL: http://127.0.0.1:8766
echo Direct MT5 test: http://127.0.0.1:8766/api/mt5/preflight
echo.
start "" "http://127.0.0.1:8766/?fresh=1"
"%AURA_PYTHON%" -m aura.webapp.server_v3 --port 8766
set "AURA_EXIT=%errorlevel%"

echo.
echo AURA stopped with exit code %AURA_EXIT%.
pause
exit /b %AURA_EXIT%

:mt5_failed
echo.
echo ERROR: MetaTrader5 Python bridge could not be imported.
echo Keep internet available and run this file again.
pause
exit /b 1

:setup_failed
echo.
echo ERROR: AURA setup failed. Check the message above.
pause
exit /b 1
