param(
    [string]$EntryName = 'Grom OCR AutoStart'
)

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if (Test-Path $runKey) {
    Remove-ItemProperty -Path $runKey -Name $EntryName -ErrorAction SilentlyContinue
}

Write-Host "Autostart removido: $EntryName"
