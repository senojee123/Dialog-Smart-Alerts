@echo off
rem Double-click to start the GIS Core Service (runs setup.ps1; needs Docker Desktop).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
