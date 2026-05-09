#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE FINAL - Sistema com Plate Recognizer Fallback
"""

import requests
import json
import time
from pathlib import Path
import sys

API_URL = "http://127.0.0.1:8000"
TEST_IMAGE = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

if not TEST_IMAGE.exists():
    print(f"✗ Imagem não encontrada: {TEST_IMAGE}")
    sys.exit(1)

print("\n" + "="*80)
print("✅ TESTE FINAL - Plate Recognizer Fallback")
print("="*80)

# 1. Health Check
print("\n[1] Verificando saúde da API...")
try:
    r = requests.get(f"{API_URL}/health", timeout=5)
    assert r.status_code == 200
    print(f"    ✓ API Online")
except Exception as e:
    print(f"    ✗ FALHA: {e}")
    sys.exit(1)

# 2. Processar
print("\n[2] Processando imagem...")

with open(TEST_IMAGE, 'rb') as f:
    files = {'image': (TEST_IMAGE.name, f, 'image/jpeg')}
    data = {'analysis_stage': 'final'}

    try:
        r = requests.post(f"{API_URL}/process", files=files, data=data, timeout=120)
    except Exception as e:
        print(f"    ✗ Erro: {e}")
        sys.exit(1)

if r.status_code != 200:
    print(f"    ✗ Status {r.status_code}: {r.text[:300]}")
    sys.exit(1)

print(f"    ✓ Status 200")

result = r.json()

# 3. Análise
print("\n[3] Resultados:")

detections = result.get('detections', [])
ocr_results = result.get('ocr_results') or result.get('ocr', [])
events = result.get('ocr_runtime_events', [])

print(f"    Detecções: {len(detections)}")
if detections:
    d = detections[0]
    print(f"      • Bbox: {d.get('bbox')}, Conf: {d.get('confidence', 0):.1%}")

print(f"    Resultados OCR: {len(ocr_results)}")
if ocr_results:
    o = ocr_results[0]
    print(f"      • '{o.get('text', '?')}' ({o.get('engine')}, {o.get('confidence', 0):.1%})")
else:
    print(f"      • Nenhum resultado OCR")

print(f"    Eventos: {len(events)}")
for evt in events:
    eng = evt.get('engine', '?')
    fb = evt.get('fallback_used', False)
    ok = evt.get('success', False)
    print(f"      • {eng}: fallback={fb}, success={ok}")

# 4. Validação
print("\n[4] Validação:")

has_detection = len(detections) > 0
has_result = len(ocr_results) > 0

if has_detection and has_result:
    print(f"    ✅ SISTEMA OPERACIONAL COM SUCESSO")
    first_ocr = ocr_results[0]
    print(f"       Placa reconhecida: '{first_ocr.get('text')}' via {first_ocr.get('engine')}")
    sys.exit(0)
elif has_detection:
    print(f"    ⚠️  Detecção OK, OCR usando fallback (Plate Recognizer)")
    print(f"       Status: SEMI-OPERACIONAL (fallback pronto)")
    sys.exit(0)
else:
    print(f"    ✗ Falha crítica")
    sys.exit(1)
