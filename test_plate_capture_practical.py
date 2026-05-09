#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE PRÁTICO: Capturar e analisar placa real com TODOS os motores de OCR
"""

import requests
import json
import time
from pathlib import Path

API_URL = "http://127.0.0.1:8000"
TEST_IMAGE = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

def test_plate_capture():
    """Teste prático de captura de placa com todos os motores habilitados."""

    if not TEST_IMAGE.exists():
        print(f"✗ Imagem não encontrada: {TEST_IMAGE}")
        return

    print("=" * 70)
    print("TESTE PRÁTICO - CAPTURA E ANÁLISE DE PLACA REAL")
    print("=" * 70)
    print(f"Imagem: {TEST_IMAGE.name}")
    print(f"API: {API_URL}")
    print()

    # Test 1: /health
    print("[1/3] Verificando saúde da API...")
    try:
        r = requests.get(f"{API_URL}/health", timeout=5)
        health = r.json()
        print(f"✓ API OK: {health}")
    except Exception as e:
        print(f"✗ API offline: {e}")
        return

    # Test 2: /process endpoint
    print("\n[2/3] Analisando placa com /process (pipeline forense delegado)...")
    try:
        with open(TEST_IMAGE, 'rb') as f:
            files = {'image': (TEST_IMAGE.name, f, 'image/jpeg')}
            data = {'analysis_stage': 'final'}

            start = time.time()
            r = requests.post(f"{API_URL}/process", files=files, data=data, timeout=120)
            duration = time.time() - start

            if r.status_code == 200:
                result = r.json()
                print(f"✓ Análise completa em {duration:.1f}s")
                print(f"  - Status: {result.get('status', 'N/A')}")
                print(f"  - OCR Text: {result.get('ocr', {}).get('text', 'N/A')}")
                print(f"  - Confidence: {result.get('ocr', {}).get('confidence', 'N/A')}")
                print(f"  - Best: {result.get('best', 'N/A')}")
                if 'orchestration' in result:
                    print(f"  - Analysis ID: {result['orchestration'].get('analysis_id')}")
                    print(f"  - Delegated: {result['orchestration'].get('tasks', {}).get('ocr', {}).get('delegated', False)}")
            else:
                print(f"✗ Erro {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"✗ Falha na requisição: {e}")

    # Test 3: /process-ensemble endpoint
    print("\n[3/3] Analisando placa com /process-ensemble (detecção em ensemble)...")
    try:
        with open(TEST_IMAGE, 'rb') as f:
            files = {'image': (TEST_IMAGE.name, f, 'image/jpeg')}
            data = {'analysis_stage': 'final'}

            start = time.time()
            r = requests.post(f"{API_URL}/process-ensemble", files=files, data=data, timeout=120)
            duration = time.time() - start

            if r.status_code == 200:
                result = r.json()
                print(f"✓ Análise ensemble completa em {duration:.1f}s")
                print(f"  - OCR Text: {result.get('ocr', {}).get('text', 'N/A')}")
                print(f"  - Confidence: {result.get('ocr', {}).get('confidence', 'N/A')}")
                if 'orchestration' in result:
                    print(f"  - Tarefas executadas: {result['orchestration'].get('task_order', [])}")
                    print(f"  - Tarefas delegadas: {sum(1 for t in result['orchestration'].get('tasks', {}).values() if t.get('delegated'))}")
            else:
                print(f"✗ Erro {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"✗ Falha na requisição: {e}")

    print("\n" + "=" * 70)
    print("FIM DO TESTE")
    print("=" * 70)

if __name__ == '__main__':
    test_plate_capture()
