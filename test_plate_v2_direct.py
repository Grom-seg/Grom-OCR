#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE FORÇADO - Chamar Plate Recognizer direto
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, r'c:\Grom_OCR')
os.chdir(r'c:\Grom_OCR')
os.environ['PLATE_RECOGNIZER_TOKEN'] = 'demo_token'

print("="*80)
print("TESTE FORÇADO - PLATE RECOGNIZER V2")
print("="*80)

from fastapi_backend.plate_recognizer_v2 import PlateRecognizerClient, recognize_plate_external

# Testar cliente v2
print("\n1. Cliente v2:")
client = PlateRecognizerClient()
print(f"   enabled: {client.enabled}")
print(f"   token: {client.api_token}")

# Testar recognize()
test_image = r'C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg'
print(f"\n2. Chamando client.recognize() com: {Path(test_image).name}")
print(f"   (Será 401 porque 'demo_token' é inválido, mas deve TENTAR chamar)")

result = client.recognize(test_image)
print(f"   Resultado: {result}")

# Testar interface pública
print(f"\n3. Chamando recognize_plate_external():")
success, plate, meta = recognize_plate_external(test_image)
print(f"   success: {success}")
print(f"   plate: {plate}")
print(f"   meta: {meta}")

print("\n" + "="*80)
print("✓ TESTE CONCLUÍDO")
print("="*80)
