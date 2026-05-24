@echo off
echo Starting DealFlow...

:: Create venv if it doesn't exist
if not exist ".venv" (
  echo Setting up virtual environment...
  python -m venv .venv
)

:: Install / update dependencies
echo Installing dependencies...
.venv\Scripts\pip install -r requirements.txt --quiet

:: Open browser after short delay
timeout /t 2 /nobreak >nul
start http://localhost:5000

:: Start Flask
echo.
echo DealFlow is running at http://localhost:5000
echo Press Ctrl+C to stop.
echo.
.venv\Scripts\python app.py
