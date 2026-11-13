param([ValidateSet('cuda','cpu')][string]$Dispositivo='cuda',[string]$PacotePerformance)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.performance-base\main.py')) {
    if (-not $PacotePerformance) {
        Add-Type -AssemblyName System.Windows.Forms
        $escolha=New-Object System.Windows.Forms.OpenFileDialog
        $escolha.Title='Selecione o VigiaAI-Performance.zip autorizado';$escolha.Filter='Pacote ZIP (*.zip)|*.zip'
        if ($escolha.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Instalação cancelada. Nenhum arquivo original foi alterado.' }
        $PacotePerformance=$escolha.FileName
    }
    & py -3.12 (Join-Path $PSScriptRoot 'integrar_base.py') --zip $PacotePerformance
    if ($LASTEXITCODE -ne 0) { throw 'A integração da base falhou. Consulte o erro; não sobreponha a versão original.' }
}
$python=Join-Path $PSScriptRoot '.venv3\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.12 -m venv (Join-Path $PSScriptRoot '.venv3')
    if ($LASTEXITCODE -ne 0) { throw 'Instale Python 3.12 x64 de python.org, sem remover o Python do original.' }
}
& $python -m pip install -r ".performance-base\requirements-$Dispositivo.txt" -r requirements-extra.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha na instalação do ambiente separado. O ambiente da apresentação não foi alterado.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependências incompatíveis; consulte o resultado acima.' }
Write-Host 'VigiaAI 3.0 instalado. Execute Iniciar-VigiaAI3.cmd e abra http://127.0.0.1:5013/banco'
