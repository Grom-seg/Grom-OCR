#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DEBUG - Verificar o que run_ocr() retorna
"""

import sys, os
from pathlib import Path

sys.path.insert(0, r'c:\Grom_OCR')
os.chdir(r'c:\Grom_OCR')

print("="*80)
print("DEBUG - O QUE run_ocr() RETORNA")
print("="*80)

# Importar run_ocr
from fastapi_backend.ocr_module import run_ocr

# Testar com a imagem de teste
test_image = r'C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg'
print(f"\nTestando: {Path(test_image).name}")

# Tentar extrair só a placa (como /process faz)
from PIL import Image
img = Image.open(test_image)

# BBox conforme teste anterior: [559, 0, 1128, 696]
x1, y1, x2, y2 = 559, 0, 1128, 696
crop = img.crop((x1, y1, x2, y2))
crop_path = '/tmp/test_crop.jpg'
crop.save(crop_path)

print(f"Crop salvo em: {crop_path}")
print(f"Tamanho crop: {crop.size}")

# Chamar run_ocr
print(f"\nChamando run_ocr('{Path(crop_path).name}')...")
result = run_ocr(crop_path)

print(f"\nResultado type: {type(result)}")
print(f"Resultado: {result}")
print(f"Resultado len: {len(result) if isinstance(result, (list, dict)) else 'N/A'}")
print(f"Resultado bool: {bool(result)}")

# Limpar
if os.path.exists(crop_path):
    os.remove(crop_path)

print("\n" + "="*80)
