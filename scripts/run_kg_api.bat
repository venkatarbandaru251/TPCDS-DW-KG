@echo off
REM Start the knowledge-graph Q&A API on http://localhost:8088.
REM Configuration (Ollama URL, model, API host/port) is read from .env —
REM see .env.example. Requires Ollama running locally with a model pulled,
REM e.g.  ollama pull llama3.1

setlocal
set REPO=%~dp0..
cd /d "%REPO%"

echo Starting KG API (config from .env)
call .venv\Scripts\python.exe -m knowledge_graph.api
