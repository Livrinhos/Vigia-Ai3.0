@echo off
cd /d "%~dp0"
if not exist ".venv3\Scripts\python.exe" (
  echo Execute Instalar.cmd uma vez para preparar as duas versoes.
  pause
  exit /b 1
)
".venv3\Scripts\python.exe" iniciar_performance.py --port 5011
pause
