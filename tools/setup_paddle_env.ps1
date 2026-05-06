param(
    [string]$ProjectRoot = "C:\Grom_OCR",
    [string]$Python311Exe = "py",
    [string]$Python311Selector = "-3.11",
    [string]$EnvName = ".venv-paddle311"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/5] Verificando Python 3.11..."
try {
    & $Python311Exe $Python311Selector --version
}
catch {
    Write-Host "Python 3.11 nao encontrado. Instale com: winget install --id Python.Python.3.11 -e"
    exit 1
}

$envPath = Join-Path $ProjectRoot $EnvName
$pythonExe = Join-Path $envPath "Scripts\python.exe"

Write-Host "[2/5] Criando ambiente virtual em $envPath ..."
& $Python311Exe $Python311Selector -m venv $envPath

if (-not (Test-Path $pythonExe)) {
    throw "Falha ao criar ambiente virtual em $envPath"
}

Write-Host "[3/5] Atualizando pip/setuptools/wheel ..."
& $pythonExe -m pip install --upgrade pip setuptools wheel

Write-Host "[4/5] Instalando stack OCR compativel..."
& $pythonExe -m pip install paddlepaddle paddleocr

Write-Host "[5/5] Instalando dependencias do backend FastAPI..."
& $pythonExe -m pip install -r (Join-Path $ProjectRoot "fastapi_backend\requirements.txt")

Write-Host "Concluido. Ative com:"
Write-Host "  & \"$envPath\Scripts\Activate.ps1\""
Write-Host "Teste rapido:"
Write-Host "  python -c \"from paddleocr import PaddleOCR; print('ok')\""
