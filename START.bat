@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

title AI Question Solver - Auto Setup
echo.
echo ============================================
echo   AI Question Solver
echo   Python + deps + login + server = AUTO
echo ============================================
echo.

set "VPY="
set "UV="

REM ---------- find or install uv (brings Python too) ----------
where uv >nul 2>&1 && set "UV=uv"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"

if not defined UV (
  echo [1/5] Setup tool ^(uv^) download ho raha hai... Internet zaroori.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
  if not defined UV if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
)

if not defined UV (
  echo [ERROR] uv install fail. Internet / antivirus check karo.
  echo Manual: https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)

echo [1/5] Setup tool ready.
echo [2/5] Python ensure ^(auto download if needed^)...
"%UV%" python install 3.12
if errorlevel 1 (
  echo [WARN] python install warning - continue try...
)

if not exist ".venv\Scripts\python.exe" (
  echo [3/5] Virtual env bana raha hoon...
  "%UV%" venv .venv --python 3.12
  if errorlevel 1 (
    "%UV%" venv .venv
  )
) else (
  echo [3/5] Virtual env pehle se ready.
)

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo [ERROR] .venv python nahi bani.
  pause
  exit /b 1
)

echo [4/5] App dependencies install / update...
"%UV%" pip install --python "%VPY%" -r requirements.txt
"%UV%" pip install --python "%VPY%" -e .
if errorlevel 1 (
  echo [ERROR] Dependency install fail.
  pause
  exit /b 1
)

echo [5/5] ChatGPT login check...
"%VPY%" -c "from app.auth import status; import sys; s=status(); print(s); sys.exit(0 if s.get('connected') else 1)"
if errorlevel 1 (
  echo.
  echo    Login zaroori hai. Browser khulega — ChatGPT se sign in karo.
  echo    Success ke baad server AUTOMATIC start hoga.
  echo.
  "%VPY%" main.py login
  if errorlevel 1 (
    echo [ERROR] Login fail. Dobara START.bat chalao.
    pause
    exit /b 1
  )
  "%VPY%" -c "from app.auth import status; import sys; s=status(); sys.exit(0 if s.get('connected') else 1)"
  if errorlevel 1 (
    echo [ERROR] Login verify fail.
    pause
    exit /b 1
  )
  echo    Login SUCCESS.
) else (
  echo    Already connected.
)

echo.
echo    Server start...  http://127.0.0.1:7860
echo    Band: Ctrl+C
echo.
start "" "http://127.0.0.1:7860"
"%VPY%" -m web.server
echo.
echo Server band.
pause
endlocal
