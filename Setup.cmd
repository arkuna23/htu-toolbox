@echo off
setlocal
cd /d "%~dp0"
title HTU Campus Network Setup

python "%~dp0scripts\setup.py"
set "exitCode=%ERRORLEVEL%"

if not "%exitCode%"=="0" (
  echo.
  echo Setup failed. Review the error above and run this file again.
  pause
)

endlocal & exit /b %exitCode%
