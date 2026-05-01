@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "RUNNER=%SCRIPT_DIR%run_benchmark_suite.py"

if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" "%RUNNER%" %*
) else (
  python "%RUNNER%" %*
)

exit /b %ERRORLEVEL%
