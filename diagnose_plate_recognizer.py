#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Diagnosticar por que Plate Recognizer não está sendo acionado
"""

import os
import sys

print("="*80)
print("DIAGNÓSTICO: Plate Recognizer Setup")
print("="*80)

# 1. Verificar env
print("\n[1] Verificando variáveis de ambiente:")
token = os.getenv('PLATE_RECOGNIZER_TOKEN', '')
print(f"    PLATE_RECOGNIZER_TOKEN: '{token}'")
print(f"    Presente: {bool(token)}")

# 2. Importar e testar
print("\n[2] Importando cliente:")
try:
    from fastapi_backend.plate_recognizer_v2 import get_plate_recognizer
    client = get_plate_recognizer()
    print(f"    ✓ Cliente importado")
    print(f"    client.enabled: {client.enabled}")
    print(f"    client.api_token: '{client.api_token}'")
    print(f"    client.api_url: {client.api_url}")
except Exception as e:
    print(f"    ✗ Erro: {e}")
    import traceback
    traceback.print_exc()

# 3. Testar função recognize_plate_external
print("\n[3] Testando recognize_plate_external:")
try:
    from fastapi_backend.plate_recognizer_v2 import recognize_plate_external
    print(f"    ✓ Função importada")

    # Verificar se main.py consegue importar
    from fastapi_backend import main
    print(f"    ✓ main.py importado")
    print(f"    _PLATE_RECOGNIZER_AVAILABLE: {main._PLATE_RECOGNIZER_AVAILABLE}")

except Exception as e:
    print(f"    ✗ Erro: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
