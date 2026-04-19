@echo off
REM Start the PHP built-in server for the dashboard.
REM Browse to http://localhost:8080/ once running.
setlocal
set REPO=%~dp0..
cd /d "%REPO%"
php -S localhost:8080 -t dashboard
