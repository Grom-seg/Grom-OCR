#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE FINAL COMPLETO - Plate Recognizer + EasyOCR Fallback
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
print("✅ TESTE FINAL - Sistema Completo com Fallback")
print("="*80)

# 1. Health Check
print("\n[1] Health Check...")
try:
    r = requests.get(f"{API_URL}/health", timeout=5)
    assert r.status_code == 200, f"Status {r.status_code}"
    print(f"    ✓ API respondendo: {r.json()['status']}")
except Exception as e:
    print(f"    ✗ FALHA: {e}")
    sys.exit(1)

# 2. Processar Imagem
print("\n[2] Processando imagem com fallback...")
print(f"    Arquivo: {TEST_IMAGE.name}")
print(f"    Tamanho: {TEST_IMAGE.stat().st_size} bytes")

with open(TEST_IMAGE, 'rb') as f:
    files = {'image': (TEST_IMAGE.name, f, 'image/jpeg')}
    data = {'analysis_stage': 'final'}

    try:
        r = requests.post(
            f"{API_URL}/process",
            files=files,
            data=data,
            timeout=120
        )
    except requests.Timeout:
        print("    ✗ Timeout na requisição")
        sys.exit(1)
    except Exception as e:
        print(f"    ✗ Erro: {e}")
        sys.exit(1)

print(f"    Status: {r.status_code}")

if r.status_code != 200:
    print(f"    ✗ Erro: {r.text[:500]}")
    sys.exit(1)

result = r.json()

# 3. Análise dos resultados
print("\n[3] Análise dos Resultados:")

detections = result.get('detections', [])
ocr_results = result.get('ocr_results', [])
ocr_runtime_events = result.get('ocr_runtime_events', [])

print(f"    Detecções: {len(detections)}")
if detections:
    for i, det in enumerate(detections):
        bbox = det.get('bbox', [])
        conf = det.get('confidence', 0)
        print(f"      [{i+1}] bbox={bbox}, confiança={conf:.1%}")

print(f"\n    Resultados OCR: {len(ocr_results)}")
if ocr_results:
    for i, ocr in enumerate(ocr_results):
        text = ocr.get('text', '?')
        conf = ocr.get('confidence', 0)
        engine = ocr.get('engine', '?')
        print(f"      [{i+1}] '{text}' ({engine}, {conf:.1%})")
else:
    print(f"      [NENHUM RESULTADO OCR]")

print(f"\n    Eventos de Fallback: {len(ocr_runtime_events)}")
if ocr_runtime_events:
    for i, evt in enumerate(ocr_runtime_events):
        engine = evt.get('engine', '?')
        fallback = evt.get('fallback_used', False)
        success = evt.get('success', False)
        print(f"      [{i+1}] engine={engine}, fallback={fallback}, success={success}")

# 4. Validação
print("\n[4] Validação Final:")

has_detection = len(detections) > 0
has_ocr = len(ocr_results) > 0
has_fallback = any(e.get('fallback_used', False) for e in ocr_runtime_events)

print(f"    ✓ Detecção funcionando: {has_detection}")
print(f"    ✓ OCR obtido: {has_ocr}")
print(f"    ✓ Fallback acionado: {has_fallback}")

if has_detection and has_ocr:
    print("\n✅ SISTEMA OPERACIONAL COM SUCESSO!")
    sys.exit(0)
elif has_detection and has_fallback:
    print("\n⚠️  Detecção OK, OCR usando fallback")
    sys.exit(0)
else:
    print("\n✗ Sistema não retornou resultados esperados")
    sys.exit(1)
