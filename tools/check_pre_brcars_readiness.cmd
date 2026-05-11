@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "CHECKER=%PROJECT_ROOT%\tools\check_pre_brcars_readiness.py"
set "REPORT=%PROJECT_ROOT%\data\datasets\brcars\pre_brcars_readiness_report.json"

if not exist "%PYTHON_EXE%" (
  echo [ERRO] Python da venv nao encontrado: "%PYTHON_EXE%"
  exit /b 1
)

if not exist "%CHECKER%" (
  echo [ERRO] Script checker nao encontrado: "%CHECKER%"
  exit /b 1
)

echo [INFO] Executando checklist pre-BRCars...
"%PYTHON_EXE%" "%CHECKER%"
set "EXIT_CODE=%ERRORLEVEL%"

if exist "%REPORT%" (
  echo [INFO] Abrindo relatorio: "%REPORT%"
  start "" "%REPORT%"
) else (
  echo [WARN] Relatorio nao encontrado em "%REPORT%"
)

exit /b %EXIT_CODE%
