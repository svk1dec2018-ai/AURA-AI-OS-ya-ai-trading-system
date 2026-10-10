@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_MT5_AURA_ALL_MARKETS.ps1"
pause
