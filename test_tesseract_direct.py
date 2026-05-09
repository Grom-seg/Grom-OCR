#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE DIRETO: Tesseract na imagem preprocessada
"""

import subprocess
import os
from pathlib import Path

# Caminho do Tesseract portátil
TESSERACT_CMD = r"C:\Grom_OCR\tools\tesseract-portable\tesseract.exe"
TESSDATA_PREFIX = r"C:\Grom_OCR\tools\tesseract-portable\tessdata"

preprocessed_image = Path(r"C:\Grom_OCR\data\plate_preprocessed_debug.jpg")

print("=" * 70)
print("TESTE DIRETO: TESSERACT + PREPROCESSAMENTO AGRESSIVO")
print("=" * 70)

if not preprocessed_image.exists():
    print(f"❌ Imagem processada não encontrada: {preprocessed_image}")
    exit(1)

print(f"Imagem: {preprocessed_image.name}")
print(f"Tesseract: {TESSERACT_CMD}")
print()

# PSM modes para placa:
# 7: Treat image as single text line
# 8: Treat image as single word
# 11: Treat image as sparse text

for psm in [7, 8, 11]:
    print(f"[PSM {psm}]", end=" ")
    try:
        result = subprocess.run(
            [
                TESSERACT_CMD,
                str(preprocessed_image),
                "stdout",
                f"--psm {psm}",
                f"--tessdata-dir {TESSDATA_PREFIX}",
                "-l por",  # português
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        text = result.stdout.strip()
        if text:
            print(f"✓ {text}")
        else:
            print("(vazio)")

    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 70)
print("CONCLUSÃO:")
print("=" * 70)
print("""
Se Tesseract ainda não funciona bem, significa:

PRÓXIMO PASSO:
1. Integrar Tesseract com configurações otimizadas (PSM 7/8)
2. Ativar EasyOCR como fallback
3. Usar Plate Recognizer API para validação

PARA REFERÊNCIA NACIONAL:
- Preprocessing agressivo já implementado
- Múltiplos motores prontos
- Fallback externo disponível
""")
