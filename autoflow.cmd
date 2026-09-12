@echo off
setlocal
"%~dp0runtime\python\python.exe" -m autoflow %*
exit /b %errorlevel%
