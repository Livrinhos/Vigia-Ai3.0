@echo off
cd /d "%~dp0"
if not exist ".venv3\Scripts\python.exe" (
  echo Execute antes Instalar-VigiaAI3.cmd.
  pause
  exit /b 1
)
".venv3\Scripts\python.exe" iniciar3.py --port 5013
pause
