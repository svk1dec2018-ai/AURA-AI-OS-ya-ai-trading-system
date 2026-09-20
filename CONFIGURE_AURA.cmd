@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_aura_env.ps1" -TemplatePath "%~dp0.env.example" -LocalPath "%~dp0.env.local"
if errorlevel 1 (
  echo.
  echo AURA env sync reported an error.
  pause
  exit /b 1
)
notepad "%~dp0.env.local"
endlocal
