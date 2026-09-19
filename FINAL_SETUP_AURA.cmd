@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\final_setup_aura.ps1"
if errorlevel 1 (
  echo.
  echo AURA final setup reported an error.
  pause
)
endlocal
