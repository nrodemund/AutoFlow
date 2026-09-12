@echo off
setlocal
cd /d "%~dp0"
"runtime\python\python.exe" -m unittest discover -s tests -v
exit /b %errorlevel%
