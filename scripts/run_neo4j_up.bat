@echo off
REM Start Neo4j 5 Community in Docker with credentials from .env.
REM Browser: http://localhost:7474  (user: NEO4J_USER, pass: NEO4J_PASSWORD)
REM Bolt:    bolt://localhost:7687

setlocal
set REPO=%~dp0..
cd /d "%REPO%"

docker compose -f infra\docker-compose.neo4j.yml --env-file .env up -d
set RC=%ERRORLEVEL%
if %RC% neq 0 (
    echo [neo4j] docker compose failed with code %RC%. Is Docker Desktop running?
    exit /b %RC%
)
echo [neo4j] Waiting for http://localhost:7474 ...
:wait
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:7474; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    timeout /t 2 /nobreak > nul
    goto wait
)
echo [neo4j] Ready — open http://localhost:7474
