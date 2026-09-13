@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel% equ 0 (
  py -3 deploy.py
) else (
  python deploy.py
)
pause
