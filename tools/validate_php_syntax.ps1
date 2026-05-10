$ErrorActionPreference = 'Stop'

# Resolve php.exe de forma robusta (evita falha por acentos no caminho do usuário).
$phpExe = $null
$phpFromCommand = (Get-Command php.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if ($phpFromCommand -and (Test-Path -LiteralPath $phpFromCommand)) {
    $phpExe = $phpFromCommand
}

if (-not $phpExe) {
    $candidate = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Filter php.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'PHP\.PHP\.8\.' } |
    Select-Object -First 1 -ExpandProperty FullName
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        $phpExe = $candidate
    }
}

if (-not $phpExe) {
    Write-Error 'PHP não encontrado automaticamente (Get-Command/WinGet Packages).'
    exit 1
}

$failed = $false

Get-ChildItem -Path . -Recurse -Filter *.php |
Where-Object { $_.FullName -notmatch '\\vendor\\' } |
ForEach-Object {
    Write-Host $_.FullName
    & $phpExe -l $_.FullName
    if ($LASTEXITCODE -ne 0) {
        $failed = $true
    }
}

if ($failed) {
    exit 1
}

exit 0
