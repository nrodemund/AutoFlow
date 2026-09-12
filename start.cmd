@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
  echo Missing bundled runtime. See README.md.
  pause
  exit /b 1
)
"runtime\python\python.exe" -m autoflow editor
set "result=%errorlevel%"
pause
exit /b %result%
