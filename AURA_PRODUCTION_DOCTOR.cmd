@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\scripts\aura_env.ps1; Import-AuraEnv -Path .\.env.local; .\.venv\Scripts\python.exe -m aura.ops.final_doctor --profile running --root ."
echo.
pause
endlocal
