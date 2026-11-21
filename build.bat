@echo off
rem One-shot setup: backend deps + frontend deps + build nine-quarter.exe
rem After this finishes, double-click nine-quarter.exe to run the project.
rem ASCII only on purpose: cmd.exe parses non-ASCII batch files unreliably.
setlocal
cd /d "%~dp0"

echo [1/5] Python virtual environment
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python not found. Install Python 3.12 from python.org, then rerun.
  goto :fail
)

echo [2/5] Backend dependencies
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [3/5] PyInstaller
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :fail

echo [4/5] Frontend dependencies
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm not found. Install Node.js 20/22 LTS from nodejs.org, then rerun.
  goto :fail
)
pushd frontend
call npm install
popd
if errorlevel 1 goto :fail

echo [5/5] Build nine-quarter.exe
".venv\Scripts\python.exe" build_exe.py
if errorlevel 1 goto :fail

echo.
echo Done. Double-click nine-quarter.exe to start.
echo First run shows a wizard: data backfill, AI config, then start services.
pause
exit /b 0

:fail
echo.
echo Setup failed. Read the messages above.
pause
exit /b 1
