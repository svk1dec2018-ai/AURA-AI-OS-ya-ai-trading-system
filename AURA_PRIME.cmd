@echo off
setlocal
cd /d "%~dp0"

:menu
cls
echo.
echo ==========================================================
echo              AURA PRIME - OWNER CONSOLE
echo ==========================================================
echo.
echo   [1] First-time setup / upgrade
echo   [2] Start AURA Prime
echo   [3] Production doctor
echo   [4] Safe auto-repair
echo   [5] Configure private credentials
echo   [6] Stop AURA Prime
echo   [7] Open dashboard
echo   [Q] Quit
echo.
choice /c 1234567Q /n /m "Select: "

if errorlevel 8 goto :eof
if errorlevel 7 goto open
if errorlevel 6 goto stop
if errorlevel 5 goto configure
if errorlevel 4 goto repair
if errorlevel 3 goto doctor
if errorlevel 2 goto start
if errorlevel 1 goto setup

:setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aura_prime.ps1" -Action Setup
pause
goto menu

:start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aura_prime.ps1" -Action Start
pause
goto menu

:doctor
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aura_prime.ps1" -Action Doctor
pause
goto menu

:repair
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aura_prime.ps1" -Action Repair
pause
goto menu

:configure
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aura_prime.ps1" -Action Configure
goto menu

:stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aura_prime.ps1" -Action Stop
pause
goto menu

:open
start "" "http://127.0.0.1:3100"
goto menu
