param(
    [int]$PhpPort = 8080,
    [switch]$PythonOnly,
    [switch]$PhpOnly
)

$ensureScript = Join-Path $PSScriptRoot 'ensure_grom_ocr_services.ps1'
if (-not (Test-Path $ensureScript)) {
    Write-Error "Script de arranque nao encontrado: $ensureScript"
    exit 1
}

& $ensureScript -PhpPort $PhpPort -PythonOnly:$PythonOnly -PhpOnly:$PhpOnly
