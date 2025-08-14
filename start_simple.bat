@echo off
echo ========================================
echo COPY TRADING BOT - SIMPLE STARTUP
echo ========================================

REM Kill any existing Python processes
echo Stopping any existing processes...
taskkill /f /im python.exe >nul 2>&1

REM Wait a moment
timeout /t 2 /nobreak >nul

echo Starting Copy Trading Bot components...

REM Start API server in background
echo Starting API Server on port 8000...
start "API Server" python -m uvicorn api:app --host 0.0.0.0 --port 8000

REM Wait for API to start
timeout /t 3 /nobreak >nul

REM Start dashboard in background
echo Starting Dashboard on port 5000...
start "Dashboard" python run_dashboard.py

REM Wait for dashboard to start
timeout /t 3 /nobreak >nul

echo.
echo ========================================
echo COMPONENTS STARTED!
echo ========================================
echo.
echo API Server: http://localhost:8000
echo Dashboard: http://localhost:5000
echo API Docs: http://localhost:8000/docs
echo.
echo Note: Copy Trading Engine needs to be started separately
echo Run: python start_bot.py
echo.
echo Press any key to stop all components...
pause >nul

echo Stopping all components...
taskkill /f /im python.exe >nul 2>&1
echo All components stopped.
