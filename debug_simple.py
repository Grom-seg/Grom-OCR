#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DEBUG simples - Testar PlateRecognizerClient"""

import os, sys
from pathlib import Path

os.chdir(r'c:\Grom_OCR')
sys.path.insert(0, r'c:\Grom_OCR')
os.environ['PLATE_RECOGNIZER_TOKEN'] = 'demo_token'

print("="*80)
print("DEBUG - PLATE RECOGNIZER")
print("="*80)

from fastapi_backend.plate_recognizer_client import PlateRecognizerClient

client = PlateRecognizerClient()
print(f"\n1. Cliente initialized:")
print(f"   enabled={client.enabled}")
print(f"   token={client.api_token[:10]}..." if client.api_token else "   token=EMPTY")

test_image = r'C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg'
print(f"\n2. Testando recognize() com: {Path(test_image).name}")

result = client.recognize(test_image)
print(f"   Resultado: {result}")

print("\n" + "="*80)
