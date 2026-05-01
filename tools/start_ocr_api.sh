#!/bin/bash
# ============================================================
# GROM_OCR — Iniciar API Python (Linux)
# Uso: bash tools/start_ocr_api.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Ativar venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Carregar .env se existir
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Configurar Tesseract (Linux usa o do sistema)
export GROM_OCR_TESSERACT_CMD="${GROM_OCR_TESSERACT_CMD:-$(which tesseract)}"

echo "=================================================="
echo "  GROM_OCR — Motor de IA Pericial"
echo "=================================================="
echo "  Tesseract: $GROM_OCR_TESSERACT_CMD"
echo "  Porta: 5000"
echo "  Modo: ${GROM_OCR_MODE:-auto}"
echo "=================================================="

# Iniciar com Waitress (produção) ou Flask (dev)
python3 tools/start_ocr_api.py
