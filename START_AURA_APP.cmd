@echo off
setlocal
cd /d "%~dp0"
title AURA AI OS - Compatibility Launcher

rem Compatibility entry point.
rem The canonical one-click launcher owns environment setup, MT5 bridge checks,
rem port cleanup, latest-main sync and the protected server_v3 PWA on 8766.

if not exist "START_AURA_AI_OS.cmd" (
  echo.
  echo ERROR: START_AURA_AI_OS.cmd was not found in this folder.
  echo Restore the repository and try again.
  echo.
  pause
  exit /b 1
)

call "START_AURA_AI_OS.cmd"
set "AURA_EXIT=%errorlevel%"
endlocal & exit /b %AURA_EXIT%
