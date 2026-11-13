param([ValidateSet('auto','cuda','cpu')][string]$Dispositivo='auto',[string]$PacotePerformance)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'VigiaAI - instalacao unica de Performance e 3.0'
try {
    & py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 indisponivel.' }
} catch { throw 'Instale Python 3.12 x64 com o Python Launcher em python.org e execute Instalar.cmd novamente.' }
# O codigo das duas versoes ja faz parte do repositorio; nenhum seletor de ZIP.
& py -3.12 (Join-Path $PSScriptRoot 'preparar_instalacao.py')
if ($LASTEXITCODE -ne 0) { throw 'Preparacao dos modelos interrompida. Consulte a mensagem acima; nenhum peso existente foi substituido.' }
if ($Dispositivo -eq 'auto') {
    $temNvidia = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
    if (-not $temNvidia) {
        $placas = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
        $temNvidia = [bool]($placas | Where-Object { $_.Name -match 'NVIDIA' })
    }
    $Dispositivo = if ($temNvidia) { 'cuda' } else { 'cpu' }
}
Write-Host "Dependencias selecionadas: $Dispositivo"
$python=Join-Path $PSScriptRoot '.venv3\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.12 -m venv (Join-Path $PSScriptRoot '.venv3')
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel criar o ambiente separado .venv3.' }
}
& $python -m pip install -r "performance\requirements-$Dispositivo.txt" -r requirements-extra.txt
if ($LASTEXITCODE -ne 0) { throw 'Instalacao de dependencias falhou; confira a internet e a mensagem acima. O ambiente original nao foi alterado.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependencias incompativeis. Consulte a mensagem acima.' }
& $python -c "import torch; print('CUDA disponivel:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
if ($LASTEXITCODE -ne 0) { throw 'A verificacao do PyTorch falhou.' }
Write-Host ''
Write-Host 'As duas versoes estao instaladas.'
Write-Host 'Iniciar-Performance.cmd  -> http://127.0.0.1:5011'
Write-Host 'Iniciar-VigiaAI3.cmd     -> http://127.0.0.1:5013/banco'
Write-Host 'Ou use Escolher-Versao.cmd. Execute uma versao por vez.'
