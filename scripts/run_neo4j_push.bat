@echo off
REM Push the knowledge graph from Postgres (graph.node/graph.edge) into Neo4j.
REM By default pushes a bounded sample (~1,700 nodes) so the Neo4j Browser
REM can render it. Pass --full to push everything (slow).

setlocal
set REPO=%~dp0..
cd /d "%REPO%"

if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set STAMP=%%i
set LOGFILE=logs\neo4j_push_%STAMP%.log

echo [%DATE% %TIME%] Pushing KG to Neo4j (args: %*) > "%LOGFILE%"
call .venv\Scripts\python.exe -m knowledge_graph.push_to_neo4j %* --wipe >> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%
echo [%DATE% %TIME%] Finished with exit code %RC% >> "%LOGFILE%"
type "%LOGFILE%"
exit /b %RC%
