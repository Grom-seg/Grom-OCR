#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE FINAL REAL - Com Plate Recognizer fallback corrigido
"""

import requests
import json
import time
from pathlib import Path

API_URL = "http://127.0.0.1:8000"
TEST_IMAGE = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

print("\n" + "="*80)
print("✅ TESTE FINAL - PLATE RECOGNIZER FALLBACK ACIONADO")
print("="*80)

# 1. Health
try:
    r = requests.get(f"{API_URL}/health", timeout=10)
    print(f"\n✓ API: {r.status_code} OK")
except Exception as e:
    print(f"\n✗ API Offline: {e}")
    exit(1)

# 2. Process
print(f"\n📸 Enviando: {TEST_IMAGE.name}")

with open(TEST_IMAGE, 'rb') as f:
    files = {'image': (TEST_IMAGE.name, f, 'image/jpeg')}
    data = {'analysis_stage': 'final'}

    print("   Processando...")
    r = requests.post(f"{API_URL}/process", files=files, data=data, timeout=120)

print(f"   Status: {r.status_code}")

if r.status_code != 200:
    print(f"   ✗ ERRO: {r.text[:300]}")
    exit(1)

result = r.json()

# 3. Resultados
print("\n" + "="*80)
print("📋 RESULTADOS")
print("="*80)

best = result.get('best', {})
print(f"\n✓ DETECÇÃO: {result.get('detections', [])[:1]}")
print(f"✓ OCR: {len(result.get('ocr', []))} candidato(s)")

if best.get('text'):
    print(f"\n✅ PLACA RECONHECIDA: {best['text']}")
    print(f"   Engine: {best.get('engine')}")
    print(f"   Score: {best.get('score'):.0%}")
else:
    print(f"\n❌ Nenhuma placa")

# Verificar se Plate Recognizer foi chamado
ocr_events = result.get('ocr_runtime_events', [])
for event in ocr_events:
    if event.get('engine') == 'plate_recognizer_api':
        print(f"\n   🔗 PLATE RECOGNIZER FALLBACK ACIONADO!")
        print(f"      Result: {event.get('result')}")

print("\n" + "="*80)
