@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_aura2_dashboard.ps1"
if errorlevel 1 (
  echo.
  echo AURA 2 startup reported an error.
  pause
)
endlocal
