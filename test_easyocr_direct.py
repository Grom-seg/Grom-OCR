#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE: EasyOCR (motor moderno e robusto)
"""

import cv2
from pathlib import Path

try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False
    print("❌ EasyOCR não instalado. Instalando...")
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "easyocr"])
    import easyocr

print("=" * 70)
print("TESTE DIRETO: EASYOCR")
print("=" * 70)

# Carregar imagem original (NÃO preprocessada)
test_image = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

if not test_image.exists():
    print(f"❌ Imagem não encontrada: {test_image}")
    exit(1)

print("Carregando modelo EasyOCR...")
reader = easyocr.Reader(['pt'], gpu=False)  # Portuguese

print(f"Processando: {test_image.name}")

# Extrair apenas a região da placa detectada
img = cv2.imread(str(test_image))
x1, y1, x2, y2 = 559, 0, 1128, 696
plate_crop = img[y1:y2, x1:x2]

# Converter de BGR para RGB
plate_rgb = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2RGB)

print("Executando OCR...")
results = reader.readtext(plate_rgb)

print("\n" + "=" * 70)
print("RESULTADOS EASYOCR:")
print("=" * 70)

if results:
    for (bbox, text, confidence) in results:
        print(f"  {text} (confidence: {confidence:.2%})")

    # Consolidar texto
    full_text = "".join([text for (_, text, _) in results])
    print(f"\nTexto consolidado: {full_text}")
else:
    print("(nenhum resultado)")

print("\n" + "=" * 70)
print("ANÁLISE:")
print("=" * 70)

if results:
    print("✓ EasyOCR funcionou!")
    print("✓ Imagem pode ser processada com motor moderno")
    print("\nPRÓXIMO PASSO: Integrar EasyOCR na API FastAPI")
else:
    print("✗ EasyOCR também retornou vazio")
    print("   Possível: imagem de teste é ruim demais, ou placa está danificada")
    print("   Solução: usar Plate Recognizer API + melhor dataset de teste")
