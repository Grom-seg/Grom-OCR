@echo off
title Launcher do Grom_OCR
color 0b

echo ==================================================
echo         INICIANDO SISTEMA FORENSE GROM_OCR
echo ==================================================
echo.

echo [1/2] Iniciando Motor de IA da Pericia (Python API na porta 5000)...
start "Grom_OCR - Motor Python" cmd /k "cd /d "%~dp0" && ".\.venv\Scripts\flask.exe" --app python/ocr_agent.py run --host=0.0.0.0 --port=5000"

echo [2/2] Iniciando Interface Web e Upload (PHP na porta 80)...
start "Grom_OCR - Servidor Web" cmd /k "cd /d "%~dp0" && php -S localhost:80 -t public"

echo.
echo Todos os motores foram estartados em janelas separadas.
echo.
echo Abra o navegador e acesse:
echo http://localhost
echo.
echo Pressione qualquer tecla para sair deste launcher.
pause >nul
