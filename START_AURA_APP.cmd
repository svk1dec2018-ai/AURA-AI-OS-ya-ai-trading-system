@echo off
setlocal
cd /d "%~dp0"
title AURA AI OS

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

where "%PYTHON_EXE%" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python was not found. Install Python 3.11+ or create .venv first.
  echo.
  pause
  exit /b 1
)

echo.
echo ==============================================
echo   AURA AI OS - LOCAL WEB APP / PWA
echo ==============================================
echo DEMO ONLY. Keep MetaTrader 5 open and logged
 echo into the DEMO account before pressing Start AURA.
echo.
echo Opening http://127.0.0.1:8765 ...
echo Close this window to stop the web app.
echo.

"%PYTHON_EXE%" -m aura.webapp.server --open
if errorlevel 1 (
  echo.
  echo AURA app stopped with an error.
  pause
)
endlocal
