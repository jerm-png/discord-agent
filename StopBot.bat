@echo off
title Stopping PerMyLastBot
echo Stopping PerMyLastBot...
powershell -Command "Get-WmiObject Win32_Process | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -like '*bot.py*'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force}"
echo Done.
timeout /t 2
exit