@echo off
setlocal
cd /d "%~dp0"
echo.
echo ============================================================
echo   AURA AI OS - One Click Ollama Multi-AI Launcher
echo   PUBLIC LIVE DATA / RESEARCH MODE - REAL MONEY DISABLED
echo ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_aura_ollama.ps1"
set "AURA_EXIT=%ERRORLEVEL%"
echo.
if not "%AURA_EXIT%"=="0" (
  echo AURA stopped with error code %AURA_EXIT%.
  echo Read the message above or send a screenshot to ChatGPT.
) else (
  echo AURA session ended normally.
)
echo.
pause
exit /b %AURA_EXIT%
