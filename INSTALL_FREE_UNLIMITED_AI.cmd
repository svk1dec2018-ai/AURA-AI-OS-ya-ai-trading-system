@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_free_unlimited_ai.ps1"
if errorlevel 1 (
  echo.
  echo Local free AI setup reported an error.
  pause
)
endlocal
