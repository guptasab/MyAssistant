@echo off
setlocal

echo [Squire] Stopping any running instances...
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8765 " ^| findstr "LISTENING"') do (
    echo [Squire] Killing PID %%p on port 8765
    taskkill /PID %%p /F /T >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [Squire] Releasing SQLite WAL locks...
if exist "data\myassistant.db-wal" del /F "data\myassistant.db-wal" >nul 2>&1
if exist "data\myassistant.db-shm" del /F "data\myassistant.db-shm" >nul 2>&1

echo [Squire] Starting assistant on http://localhost:8765
echo [Squire] Admin UI: http://localhost:8765/admin
echo [Squire] Chat UI:  http://localhost:8765/pwa/
echo.

call .venv\Scripts\activate.bat 2>nul || (
    echo [Squire] ERROR: .venv not found. Run: python -m venv .venv ^&^& .venv\Scripts\pip install -e .
    pause
    exit /b 1
)

python -m myassistant run --channel all
