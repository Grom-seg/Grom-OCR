#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TESTE: Usar Plate Recognizer (API externa) para validar que a placa CAN be read
"""

import requests
import json
import os
from pathlib import Path

TEST_IMAGE = Path(r"C:\Grom_OCR\data\uploads\20171119_154214_ch6-1024x576.jpg")

# Plate Recognizer é um serviço REST - vamos testar se conseguimos capturar
print("=" * 70)
print("TESTE: USAR PLATE RECOGNIZER PARA VALIDAR CAPTURA")
print("=" * 70)

# Se não tiver token, apenas mostramos o processo
token = os.getenv('PLATE_RECOGNIZER_TOKEN', 'demo_token')
api_url = 'https://api.platerecognizer.com/v1/plate-reader/'

if token == 'demo_token':
    print("\n⚠️  Sem token Plate Recognizer configurado")
    print("   Método: GROM OCR local com múltiplos motores")
    print("   Próximos passos:")
    print("     1. Importar Plate Recognizer como fallback externo")
    print("     2. Ativar EasyOCR/RapidOCR/PaddleOCR localmente")
    print("     3. Usar preprocessamento agressivo para melhorar qualidade")
else:
    print(f"\n✓ Usando Plate Recognizer com token...")
    try:
        with open(TEST_IMAGE, 'rb') as f:
            response = requests.post(
                api_url,
                files={'upload': f},
                headers={'Authorization': f'Token {token}'},
                timeout=30
            )

        if response.status_code == 200:
            result = response.json()
            print(f"✓ Resultado: {json.dumps(result, indent=2)}")
        else:
            print(f"✗ Erro {response.status_code}: {response.text}")
    except Exception as e:
        print(f"✗ Falha: {e}")

print("\n" + "=" * 70)
print("ANÁLISE DO PROBLEMA:")
print("=" * 70)
print("""
✓ Placa FOI DETECTADA (63% confiança)
✗ OCR LOCAL RETORNOU VAZIO (Tesseract sozinho não funciona bem)

SOLUÇÃO:
1. Importar Plate Recognizer API (excelente para Brazilian plates)
2. Usar MÚLTIPLOS motores locais (EasyOCR, RapidOCR, PaddleOCR)
3. Preprocessing AGRESSIVO:
   - Binarização adaptativa
   - Contraste dinâmico
   - Remoção de ruído
   - Aumento de resolução

IMPLEMENTAR AGORA: Melhorias locais + Plate Recognizer como fallback
""")
