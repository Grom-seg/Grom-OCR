#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Testar diretamente recognize_plate_external
"""

from pathlib import Path

# Carregar .env
import os
_env_path = Path(__file__).parent / '.env'
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                if key not in os.environ:
                    os.environ[key] = value.strip()

from fastapi_backend.plate_recognizer_v2 import recognize_plate_external

TEST_IMAGE = r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg"

print("Testando recognize_plate_external...")
print(f"  Imagem: {TEST_IMAGE}")

if not Path(TEST_IMAGE).exists():
    print(f"  ✗ Arquivo não encontrado")
    exit(1)

try:
    print(f"\n  Chamando API...")
    success, plate_text, metadata = recognize_plate_external(TEST_IMAGE)

    print(f"  Sucesso: {success}")
    print(f"  Placa: {plate_text}")
    print(f"  Metadata: {metadata}")

    if success:
        print(f"\n✅ PLATE RECOGNIZER FUNCIONANDO!")
    else:
        print(f"\n⚠️  Retornou False (possível credencial inválida)")

except Exception as e:
    print(f"  ✗ Erro: {e}")
    import traceback
    traceback.print_exc()
