param(
    [string]$EntryName = 'Grom OCR AutoStart'
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $projectRoot 'tools\ensure_grom_ocr_services.ps1'

if (-not (Test-Path $runner)) {
    throw "Script de arranque nao encontrado: $runner"
}

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if (-not (Test-Path $runKey)) {
    New-Item -Path $runKey -Force | Out-Null
}

$command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $runner + '"'
Set-ItemProperty -Path $runKey -Name $EntryName -Value $command

Write-Host "Autostart registrado no login do Windows: $EntryName"
Write-Host "Comando: $command"
