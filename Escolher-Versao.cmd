@echo off
cd /d "%~dp0"
echo 1 - VigiaAI Performance
echo 2 - VigiaAI 3.0 - Banco de Imagens e Treinamento
choice /C 12 /N /M "Escolha a versao: "
if errorlevel 2 (
  call "%~dp0Iniciar-VigiaAI3.cmd"
) else (
  call "%~dp0Iniciar-Performance.cmd"
)
