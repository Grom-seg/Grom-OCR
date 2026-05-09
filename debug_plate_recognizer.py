#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DEBUG - Testar PlateRecognizerClient diretamente
"""

import os
import sys
from pathlib import Path

# Forçar carregamento .env
sys.path.insert(0, r'c:\Grom_OCR')
os.chdir(r'c:\Grom_OCR')

# Carregar .env
from dotenv import load_dotenv
load_dotenv('.env')

# Configurar token manualmente
os.environ['PLATE_RECOGNIZER_TOKEN'] = 'demo_token'

print("="*80)
print("DEBUG - PLATE RECOGNIZER CLIENT")
print("="*80)

# Verificar token
token = os.getenv('PLATE_RECOGNIZER_TOKEN', '')
print(f"\n1. Token configurado: {bool(token)}")
print(f"   Valor: {token[:30] if token else '[vazio]'}")

# Importar cliente
try:
    from fastapi_backend.plate_recognizer_client import PlateRecognizerClient, recognize_plate_external
    print(f"\n2. Importação: ✓ OK")
except Exception as e:
    print(f"\n2. Importação: ✗ ERRO")
    print(f"   {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Testar cliente
client = PlateRecognizerClient()
print(f"\n3. Cliente PlateRecognizerClient:")
print(f"   enabled: {client.enabled}")
print(f"   api_token: {client.api_token[:20] if client.api_token else '[vazio]'}")
print(f"   api_url: {client.api_url}")
print(f"   timeout: {client.timeout}s")

# Testar com imagem
test_image = Path(r'C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg')
if test_image.exists():
    print(f"\n4. Testando com imagem: {test_image.name}")
    print(f"   Tamanho: {test_image.stat().st_size / 1024:.1f} KB")

    # Tentar reconhecer
    print(f"\n   Chamando client.recognize()...")
    try:
        result = client.recognize(str(test_image))
        if result:
            print(f"\n   ✓ Requisição OK (status 200)")
            print(f"   Resposta resumida: {str(result)[:200]}")
        else:
            print(f"\n   ⚠️  Requisição retornou None")
            print(f"      (Pode significar: token inválido, API indisponível, etc)")
    except Exception as e:
        print(f"\n   ✗ Erro na requisição:")
        print(f"   {type(e).__name__}: {e}")
else:
    print(f"\n4. Imagem não encontrada: {test_image}")

# Testar interface pública
print(f"\n5. Testando recognize_plate_external():")
try:
    success, plate, meta = recognize_plate_external(str(test_image))
    print(f"   success: {success}")
    print(f"   plate: {plate}")
    print(f"   meta: {meta}")
except Exception as e:
    print(f"   Erro: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("✓ DEBUG CONCLUÍDO")
print("="*80)
