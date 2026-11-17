@echo off
setlocal
if not exist "%~dp0launch.ps1" (
    echo FitPlate is incomplete. Extract the full project folder before starting it.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
set "FITPLATE_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %FITPLATE_EXIT_CODE%
