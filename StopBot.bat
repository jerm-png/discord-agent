@echo off
title Stopping PerMyLastBot
echo Stopping PerMyLastBot...
taskkill /F /FI "WINDOWTITLE eq PerMyLastBot" /T
if %errorlevel% == 0 (
    echo PerMyLastBot stopped successfully.
) else (
    echo No PerMyLastBot process found.
)
timeout /t 2
exit