@echo off
REM Build (or refresh) the knowledge graph in the `graph` Postgres schema.
REM Idempotent — safe to re-run after each pipeline refresh.

setlocal
set REPO=%~dp0..
cd /d "%REPO%"

if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set STAMP=%%i
set LOGFILE=logs\kg_build_%STAMP%.log

echo [%DATE% %TIME%] Building knowledge graph > "%LOGFILE%"
call .venv\Scripts\python.exe -m knowledge_graph.build_graph >> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%
echo [%DATE% %TIME%] Finished with exit code %RC% >> "%LOGFILE%"
exit /b %RC%
