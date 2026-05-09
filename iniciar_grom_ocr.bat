@echo off
title Launcher do Grom_OCR
color 0b

echo ==================================================
echo         INICIANDO SISTEMA FORENSE GROM_OCR
echo ==================================================
echo.

echo [1/2] Iniciando Motor de IA da Pericia (FastAPI na porta 8000)...
start "Grom_OCR - Motor Python" cmd /k "cd /d "%~dp0" && ".\.venv\Scripts\python.exe" tools\start_ocr_api.py"

echo [2/2] Iniciando Interface Web e Upload (PHP na porta 8080)...
start "Grom_OCR - Servidor Web" cmd /k "cd /d "%~dp0" && set GROM_OCR_PYTHON_API_URL=http://127.0.0.1:8000 && php -S 127.0.0.1:8080 -t public"

echo.
echo Todos os motores foram estartados em janelas separadas.
echo.
echo Abra o navegador e acesse:
echo http://127.0.0.1:8080
echo.
echo Pressione qualquer tecla para sair deste launcher.
pause >nul
