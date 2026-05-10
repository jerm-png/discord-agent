@echo off
echo This will install Ollama as a Windows scheduled task
echo that auto-starts on login and restarts if it crashes.
echo.
echo Run this once as Administrator.
echo.

schtasks /create /tn "OllamaService" /tr "%~dp0StartOllama.bat" /sc onlogon /ru "%USERNAME%" /f
if %errorlevel% == 0 (
    echo.
    echo Success — Ollama will now auto-start on login.
    echo To remove it later run: schtasks /delete /tn "OllamaService" /f
) else (
    echo.
    echo Failed — make sure you ran this as Administrator.
    echo Right-click InstallOllamaService.bat and choose
    echo "Run as administrator"
)
pause
