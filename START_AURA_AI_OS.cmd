@echo off
setlocal EnableExtensions
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
  echo [1/4] Checking latest AURA main branch...
  git pull --ff-only origin main
  if errorlevel 1 (
    echo.
    echo WARNING: Git fast-forward update was not completed.
    echo AURA will continue with the local files already on this PC.
    echo.
  )
) else (
  echo [1/4] Git not found - using current local AURA files.
)

set "AURA_PYTHON="
if exist ".venv\Scripts\python.exe" set "AURA_PYTHON=.venv\Scripts\python.exe"
if not defined AURA_PYTHON (
  where py >nul 2>&1
  if %errorlevel%==0 set "AURA_PYTHON=py -3.11"
)
if not defined AURA_PYTHON (
  where python >nul 2>&1
  if %errorlevel%==0 set "AURA_PYTHON=python"
)

if not defined AURA_PYTHON (
  echo.
  echo ERROR: Python was not found.
  echo Install Python 3.11 or newer, then double-click this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [2/4] Creating local AURA Python environment...
  %AURA_PYTHON% -m venv .venv
  if errorlevel 1 goto :setup_failed
  set "AURA_PYTHON=.venv\Scripts\python.exe"
  echo [3/4] Installing AURA locally...
  "%AURA_PYTHON%" -m pip install --disable-pip-version-check -e .
  if errorlevel 1 goto :setup_failed
) else (
  echo [2/4] Local Python environment ready.
  echo [3/4] AURA package available from this repository.
)

echo [4/4] Opening AURA AI OS...
echo.
echo Browser address: http://127.0.0.1:8765
echo Close this window only when you want to stop the local web server.
echo Trading itself is controlled from the AURA Trading Desk.
echo.
"%AURA_PYTHON%" -m aura.webapp.server --open
set "AURA_EXIT=%errorlevel%"

echo.
if not "%AURA_EXIT%"=="0" (
  echo AURA exited with code %AURA_EXIT%.
  echo Check the message above, then run this launcher again.
) else (
  echo AURA stopped normally.
)
pause
exit /b %AURA_EXIT%

:setup_failed
echo.
echo ERROR: AURA setup could not be completed automatically.
echo Check your internet/Python installation and run this launcher again.
pause
exit /b 1
