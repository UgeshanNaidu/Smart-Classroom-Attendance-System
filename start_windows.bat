@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.10 or later from python.org or microsoft store, then try again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check your internet connection.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8080 in your browser.
.venv\Scripts\python.exe httpserver.py --demo
pause
