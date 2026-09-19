@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_aura_fleet.ps1"
if errorlevel 1 (
  echo.
  echo AURA Fleet startup reported an error.
  pause
)
endlocal
