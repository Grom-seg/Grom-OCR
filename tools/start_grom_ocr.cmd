@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\tools\ensure_grom_ocr_services.ps1"
if errorlevel 1 (
    echo [ERRO] Nao foi possivel iniciar os servicos automaticamente.
    exit /b 1
)

echo [OK] Rotina de arranque automatizado executada.

endlocal
