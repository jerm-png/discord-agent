@echo off
title PerMyLastBot
cd /d C:\Projects\discord-agent\agents
call ..\venv\Scripts\activate
echo Starting PerMyLastBot...
echo Checking Ollama...
curl -s http://localhost:11434 > nul 2>&1
if %errorlevel% neq 0 (
    echo Ollama not running — starting it now...
    start "" "%~dp0StartOllama.bat"
    timeout /t 4 /nobreak > nul
    echo Ollama started.
) else (
    echo Ollama already running.
)
echo.
python -X utf8 bot.py
pause