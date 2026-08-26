@echo off
cd /d "%~dp0"
echo LOGIN ab START.bat ke andar automatic hai.
echo Agar alag se login chahiye:
if not exist ".venv\Scripts\python.exe" (
  echo Pehle START.bat chalao.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py login
pause
