#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE DIRETO: Capturar resposta exata da API
"""

import requests
import json
from pathlib import Path

API_URL = "http://127.0.0.1:8000"
TEST_IMAGE = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

print("Enviando requisição para /process...")
with open(TEST_IMAGE, 'rb') as f:
    files = {'image': (TEST_IMAGE.name, f, 'image/jpeg')}
    data = {'analysis_stage': 'final'}

    r = requests.post(f"{API_URL}/process", files=files, data=data, timeout=120)

print(f"Status: {r.status_code}")
print(f"Response type: {type(r.json())}")
print("\n" + "=" * 70)
print("RESPOSTA COMPLETA:")
print("=" * 70)
print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:2000])
print("\n... [truncado]\n")

# Extrair e exibir result ados práticos
result = r.json()
if isinstance(result, list):
    print(f"Retornou uma LISTA com {len(result)} itens:")
    for i, item in enumerate(result[:3]):
        print(f"  [{i}] {json.dumps(item, indent=4, ensure_ascii=False)[:300]}")
elif isinstance(result, dict):
    print("Retornou DICIONÁRIO:")
    if 'ocr' in result:
        print(f"  OCR Text: {result['ocr'].get('text', 'N/A')}")
        print(f"  OCR Confidence: {result['ocr'].get('confidence', 'N/A')}")
    if 'best' in result:
        print(f"  Best Result: {result['best']}")
