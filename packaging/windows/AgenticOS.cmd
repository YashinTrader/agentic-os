@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-AgenticOS.ps1" -AppRoot "%~dp0." %*
exit /b %errorlevel%
