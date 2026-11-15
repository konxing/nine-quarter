@echo off
rem nine-quarter launcher: backend on 8000, frontend on 3100
rem ASCII only on purpose: cmd.exe parses non-ASCII batch files unreliably.
setlocal
cd /d "%~dp0"

netstat -ano | findstr /r "127\.0\.0\.1:8000 .*LISTENING" >nul
if %errorlevel%==0 (
  echo WARNING: port 8000 is already in use.
  echo An older backend is probably still running. Close that window first
  echo ^(or run: netstat -ano ^| findstr :8000, then taskkill /PID ^<pid^> /F^).
  echo.
)

netstat -ano | findstr /r "127\.0\.0\.1:3100 .*LISTENING" >nul
if %errorlevel%==0 (
  echo WARNING: port 3100 is already in use. Close the old frontend window first.
  echo.
)

start "nine-quarter backend" cmd /k ".venv\Scripts\python.exe -m backend.cli serve --port 8000"
start "nine-quarter frontend" cmd /k "pushd frontend && npm run dev"

echo Backend API : http://127.0.0.1:8000
echo Frontend    : http://127.0.0.1:3100
echo AI settings : http://127.0.0.1:3100/settings
echo.
echo Two new windows should appear. Keep them open; closing one stops that process.
pause
