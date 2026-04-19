@echo off
REM Daily Bronze ingest + dbt source tests. Logs to logs/ingest_YYYY-MM-DD.log.
REM Intended target: Windows Task Scheduler, daily ~5:00 AM (before CEO's 7 AM SLA).

setlocal
set REPO=%~dp0..
cd /d "%REPO%"

if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set STAMP=%%i
set LOGFILE=logs\ingest_%STAMP%.log

echo [%DATE% %TIME%] Starting daily ingest > "%LOGFILE%"
call .venv\Scripts\python.exe -m ingestion.run_pipeline >> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%
echo [%DATE% %TIME%] Finished with exit code %RC% >> "%LOGFILE%"
exit /b %RC%
