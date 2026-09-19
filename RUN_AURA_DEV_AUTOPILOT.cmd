@echo off
setlocal
cd /d "%~dp0"
title AURA AI OS - DEV AUTOPILOT

echo ============================================================
echo               AURA AI OS - DEV AUTOPILOT
echo ============================================================
echo.
echo This runs the existing AURA repository through an autonomous
 echo audit - test - fix - regression - checkpoint loop using Claude Code.
echo MT5 remains DEMO-only and fund movement stays blocked.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_AURA_DEV_AUTOPILOT.ps1"
set "AURA_EXIT=%errorlevel%"

echo.
if "%AURA_EXIT%"=="0" (
  echo AURA DEV AUTOPILOT run finished.
) else (
  echo AURA DEV AUTOPILOT stopped with exit code %AURA_EXIT%.
)
echo Check runtime\dev_autopilot for the full log.
echo.
pause
exit /b %AURA_EXIT%
