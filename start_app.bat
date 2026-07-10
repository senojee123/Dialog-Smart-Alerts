@echo off
title Dialog Smart Alerts Launcher
echo ===================================================
echo             DIALOG SMART ALERTS LAUNCHER           
echo ===================================================
echo.
echo Launching services in separate windows...
echo.

:: 1. Start backend server
echo [1/2] Starting Backend Server (FastAPI)...
start "Dialog Alerts Backend" cmd /k "python backend/server.py"

:: 2. Start frontend dev server
echo [2/2] Starting Frontend Server (Vite)...
start "Dialog Alerts Frontend" cmd /k "npm run dev"

echo.
echo ===================================================
echo  All services have been launched!                  
echo.
echo  - Frontend Dashboard : http://localhost:5173      
echo  - Backend API        : http://localhost:8000      
echo ===================================================
echo.
echo Press any key to close this launcher window (services will keep running).
pause > nul
