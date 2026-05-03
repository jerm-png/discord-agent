@echo off
title PerMyLastBot
cd /d C:\Projects\discord-agent\agents
call ..\venv\Scripts\activate
echo Starting PerMyLastBot...
python -X utf8 bot.py
pause