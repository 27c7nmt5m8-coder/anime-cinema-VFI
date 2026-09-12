@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please follow the Windows setup in README.md first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m animecinemavfi
